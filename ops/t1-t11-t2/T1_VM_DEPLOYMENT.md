# T1 — DeepSeek Harness AWS VM 배포 및 기본 동작 검증

## 1. 목적

T1의 목적은 DeepSeek Harness를 Linux VM 환경에 실제로 배포하고, 원격 환경에서도 정상적으로 실행되는지 검증하는 것이다.

이번 단계에서는 성능 최적화나 동시 사용자 부하 테스트를 수행하지 않는다.

검증 범위는 다음과 같다.

- AWS EC2 VM 생성
- Ubuntu 환경 구성
- DeepSeek Harness Source 설치 및 Build
- Harness Web UI 실행
- SSH Tunnel을 통한 원격 접속
- LLM 응답 확인
- Tool Call / Tool Result 확인
- VM Workspace 접근 확인
- T11 비교용 CPU / Memory / Disk Baseline 측정

전체 테스트 흐름은 다음과 같다.

```text
T1 VM 배포
    ↓
T11 동시 사용자 부하 테스트
    ↓
T2 규모 테스트
```

---

# 2. 테스트 구성

## 2.1 네트워크 구조

```text
Windows 개발 PC
      │
      │ SSH :22
      ↓
AWS EC2 Ubuntu VM
      │
      │ 127.0.0.1:3080
      ↓
DeepSeek Harness Web

Windows Browser
127.0.0.1:3080
      ↑
SSH Local Port Forwarding
```

Harness의 `3080` 포트는 인터넷에 직접 공개하지 않는다.

대신 SSH Tunnel을 통해 개발 PC에서만 Web UI에 접근한다.

---

# 3. AWS EC2 설정

## 3.1 최종 테스트 환경

| 항목 | 설정 |
|---|---|
| Cloud | AWS EC2 |
| Instance Name | `deepseek-harness-t1` |
| OS | Ubuntu Server 24.04 LTS x86_64 |
| Instance Type | `t3.medium` |
| Storage | 30 GiB gp3 |
| Public IP | 활성화 |
| Security Group | `deepseek-harness-t1-sg` |
| Inbound | SSH TCP 22 / My IP |
| HTTP 80 | 비활성화 |
| HTTPS 443 | 비활성화 |
| Harness 3080 | 외부 미개방 |
| Swap | 4 GiB |

## 3.2 각 설정을 선택한 이유

### Ubuntu Server 24.04 LTS

Node.js, Git, pnpm 등 Harness 개발 환경을 구성하기 쉽고 LTS 버전이므로 테스트 환경을 안정적으로 유지하기 위해 사용한다.

### t3.medium

처음에는 비용 절감을 위해 `t3.small`로 테스트했다.

`t3.small`에서도 Dependency 설치는 정상적으로 수행되었지만 약 2 GiB의 RAM 환경에서 TypeScript Build가 Swap에 크게 의존하면서 Build 시간이 매우 길어졌다.

따라서 실제 T1 검증 환경은 `t3.medium`으로 변경하였다.

```text
t3.small
약 2 GiB RAM
↓
Build 과정에서 Swap 의존 증가
↓
t3.medium으로 변경
↓
Build 정상 완료
```

### 30 GiB gp3

Ubuntu OS, Git Repository, `node_modules`, Build Artifact 등을 저장할 수 있는 충분한 공간을 확보하면서 과도한 Storage를 할당하지 않기 위해 30 GiB를 사용한다.

### Public IP 활성화

개발 PC에서 EC2에 SSH로 접속해야 하므로 T1 단계에서는 Public IP가 필요하다.

### SSH 22 / My IP만 허용

VM 관리에 필요한 SSH만 외부에서 허용한다.

접속 가능한 Source 또한 현재 개발 PC의 IP로 제한하여 외부 노출을 줄인다.

### HTTP / HTTPS 미개방

이번 T1에서는 일반 Web Service를 외부에 공개하는 것이 목적이 아니므로 80 / 443 포트를 열지 않는다.

### Harness 3080 미개방

Harness Web UI는 SSH Tunnel을 이용해 접근하므로 Security Group에서 3080 포트를 외부에 공개하지 않는다.

---

# 4. Windows에서 EC2 SSH 접속

AWS에서 생성한 Key Pair 파일을 사용한다.

이번 테스트에서는 다음 PEM 파일을 사용하였다.

```text
deepseek-harness-t1.pem
```

PEM 파일이 Windows의 Downloads 폴더에 있는 경우 다음과 같이 이동한다.

```powershell
cd $HOME\Downloads
```

### 명령어 의미

- `cd`  
  현재 작업 Directory를 변경한다.

- `$HOME`  
  현재 Windows 사용자의 Home Directory를 의미한다.

이번 환경에서는 다음과 같은 경로이다.

```text
C:\Users\user
```

따라서:

```powershell
cd $HOME\Downloads
```

는 다음 폴더로 이동한다는 의미이다.

```text
C:\Users\user\Downloads
```

이후 SSH로 EC2에 접속한다.

```powershell
ssh -i "deepseek-harness-t1.pem" ubuntu@<EC2-Public-DNS>
```

### 명령어 의미

`ssh`

원격 Linux 서버에 암호화된 Terminal 연결을 생성한다.

`-i`

SSH 인증에 사용할 Private Key 파일을 지정한다.

```text
-i "deepseek-harness-t1.pem"
```

`ubuntu`

Ubuntu EC2 AMI의 기본 사용자 계정이다.

`<EC2-Public-DNS>`

인터넷에서 EC2 Instance를 찾기 위한 Public DNS 주소이다.

---

# 5. Swap 설정

초기 `t3.small` 환경에서 메모리 부족으로 Process가 종료되는 것을 방지하기 위해 4 GiB Swap을 추가하였다.

```bash
sudo fallocate -l 4G /swapfile
```

### 의미

- `sudo`  
  관리자 권한으로 실행한다.

- `fallocate`  
  Disk 공간을 파일에 미리 할당한다.

- `-l 4G`  
  파일 크기를 4 GiB로 설정한다.

- `/swapfile`  
  생성할 Swap 파일 위치이다.

즉 Disk에 4 GiB 크기의 Swap 파일을 생성한다.

---

Swap 파일의 권한을 제한한다.

```bash
sudo chmod 600 /swapfile
```

`600`은 파일 소유자만 읽기와 쓰기가 가능하다는 의미이다.

Swap에는 Memory 내용이 기록될 수 있으므로 다른 사용자가 접근하지 못하도록 제한한다.

---

Swap 파일을 Linux Swap 형식으로 초기화한다.

```bash
sudo mkswap /swapfile
```

---

Swap을 활성화한다.

```bash
sudo swapon /swapfile
```

---

재부팅 이후에도 자동으로 활성화되도록 설정한다.

```bash
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### 의미

`echo`

설정 문자열을 출력한다.

`|`

앞 명령의 출력을 다음 명령의 입력으로 전달하는 Pipe이다.

`tee -a`

파일의 기존 내용을 유지하면서 마지막에 새로운 내용을 추가한다.

`/etc/fstab`

Linux 부팅 시 자동으로 Mount하거나 활성화할 Disk / Swap 정보를 저장하는 설정 파일이다.

---

Swap 상태를 확인한다.

```bash
free -h
```

`-h`는 Memory 값을 GiB / MiB처럼 사람이 읽기 쉬운 단위로 표시한다.

실제 확인 결과:

```text
Mem:   약 1.9 GiB
Swap:  4.0 GiB
```

---

# 6. Ubuntu 기본 개발 환경 설치

먼저 Package 목록을 최신 상태로 갱신한다.

```bash
sudo apt update
```

`apt update`는 프로그램 자체를 Upgrade하는 명령이 아니라 Ubuntu가 설치 가능한 Package 목록을 최신 상태로 가져오는 명령이다.

---

필요한 개발 도구를 설치한다.

```bash
sudo apt install -y git curl ca-certificates build-essential python3
```

각 Package의 역할은 다음과 같다.

| Package | 역할 |
|---|---|
| `git` | GitHub Repository Clone 및 Version 관리 |
| `curl` | URL에서 설치 Script 또는 데이터 다운로드 |
| `ca-certificates` | HTTPS 인증서 검증 |
| `build-essential` | GCC, Make 등 Native Module Build 도구 |
| `python3` | Python 실행 환경 |

`-y`는 설치 확인 질문에 자동으로 Yes를 입력한다.

---

설치 결과를 확인한다.

```bash
git --version
python3 --version
free -h
```

실제 환경:

```text
Git     2.43.0
Python  3.12.3
```

---

# 7. Node.js 24 설치

NodeSource Repository를 등록한다.

```bash
curl -fsSL https://deb.nodesource.com/setup_24.x | sudo -E bash -
```

### curl 옵션

`-f`

HTTP 오류 발생 시 실패 처리한다.

`-s`

불필요한 진행 출력을 줄인다.

`-S`

Silent Mode에서도 오류는 출력한다.

`-L`

Redirect가 발생하면 따라간다.

다운로드한 설치 준비 Script를 Pipe를 통해 Bash에 전달하여 실행한다.

---

Node.js를 설치한다.

```bash
sudo apt install -y nodejs
```

설치 확인:

```bash
node -v
npm -v
```

실제 테스트 결과:

```text
Node.js v24.21.0
npm     11.19.0
```

---

# 8. pnpm 설치

Harness Repository에서 사용하는 pnpm 버전을 설치한다.

```bash
sudo npm install -g pnpm@11.7.0
```

### 의미

`npm install`

npm Package를 설치한다.

`-g`

특정 Project 내부가 아니라 시스템 전체에서 사용할 수 있도록 Global 설치한다.

`pnpm@11.7.0`

설치할 pnpm Version을 정확히 지정한다.

---

확인:

```bash
pnpm -v
```

결과:

```text
11.7.0
```

---

# 9. DeepSeek Harness Repository Clone

Home Directory로 이동한다.

```bash
cd ~
```

Repository를 Clone한다.

```bash
git clone https://github.com/Text-To-SQL-Agent/deepseek-harness.git
```

Project Directory로 이동한다.

```bash
cd deepseek-harness
```

---

현재 Branch와 Commit을 확인할 수 있다.

```bash
git branch --show-current
git rev-parse --short HEAD
```

### 의미

`git branch --show-current`

현재 Checkout된 Branch 이름을 확인한다.

`git rev-parse --short HEAD`

현재 사용 중인 Commit SHA를 짧은 형식으로 출력한다.

성능 테스트 시 어떤 Source Code Version을 사용했는지 기록하기 위해 중요하다.

---

## Branch 관련 주의

T1 수행 당시 로컬 PC의:

```text
feature/t1-t11-t2-validation
```

Branch는 GitHub에 Push하지 않은 상태였다.

따라서 VM에서는 원격 Repository에 존재하는 코드를 기준으로 배포 검증을 수행하였다.

---

# 10. Dependency 설치

```bash
pnpm install --frozen-lockfile
```

### 의미

`pnpm install`

Repository에서 필요한 Node.js Dependency를 설치한다.

`--frozen-lockfile`

`pnpm-lock.yaml`을 변경하지 않고 Lockfile에 저장된 정확한 Dependency Version을 그대로 설치한다.

VM마다 다른 Version이 설치되는 것을 방지하여 테스트 재현성을 높인다.

---

실제 결과:

```text
Done in 45.7s using pnpm v11.7.0
```

Memory 상태 확인:

```bash
free -h
```

---

# 11. Harness Source Build

Project Directory로 이동한다.

```bash
cd ~/deepseek-harness
```

`~`는 현재 Ubuntu 사용자의 Home Directory이다.

이번 환경에서는:

```text
/home/ubuntu
```

따라서:

```text
~/deepseek-harness
```

는:

```text
/home/ubuntu/deepseek-harness
```

를 의미한다.

---

Build를 실행한다.

```bash
pnpm run build
```

이 명령은 `package.json`에 정의된 Build Script를 실행한다.

Harness의 TypeScript Compile, Native Module Build, Host / Client Artifact 생성 등이 수행된다.

---

## 11.1 t3.small Build 문제

`t3.small` 환경에서는 다음 단계에서 Build가 매우 오래 걸렸다.

```text
node --max-old-space-size=4096 ...
tsc -b tsconfig.host.json
```

Node Process는 최대 4 GiB Heap을 사용할 수 있도록 설정되어 있었지만 실제 Instance RAM은 약 2 GiB였다.

따라서 부족한 Memory를 Swap으로 처리하면서 Build 성능이 크게 저하되었다.

---

## 11.2 t3.medium으로 변경

AWS EC2에서:

```text
Instance Stop
→ Instance Type 변경
→ t3.medium
→ Instance Start
```

순서로 변경하였다.

EBS Storage는 그대로 유지되므로 Repository와 Dependency를 다시 설치할 필요는 없다.

다시 Build:

```bash
cd ~/deepseek-harness
pnpm run build
```

실제 결과:

```text
✓ built in 8.29s
build: recorded 234 client artifact(s) with 2 public value(s)
```

---

Build 성공 여부를 Exit Code로 확인한다.

```bash
echo $?
```

Linux에서 `$?`는 직전에 실행한 명령의 종료 코드이다.

```text
0
```

이면 정상 종료이다.

실제 결과:

```text
0
```

따라서:

```text
Source Build = PASS
```

로 판단하였다.

---

# 12. T1 전용 Harness Home 설정

T1 테스트 전용 Directory를 생성한다.

```bash
mkdir -p "$HOME/dsh-t1-home"
```

### 의미

`mkdir`

Directory를 생성한다.

`-p`

상위 Directory가 필요하면 같이 생성하고 이미 Directory가 존재해도 오류를 발생시키지 않는다.

---

Harness Home 환경 변수를 지정한다.

```bash
export DSH_HOME="$HOME/dsh-t1-home"
```

`export`는 현재 Shell과 해당 Shell에서 실행되는 Process가 사용할 Environment Variable을 설정한다.

T1 테스트 설정과 다른 Harness 환경을 분리하기 위해 별도의 `DSH_HOME`을 사용하였다.

---

# 13. Harness Web 실행

```bash
pnpm dsh web --no-open
```

### 의미

`pnpm dsh`

현재 Repository Source에서 DeepSeek Harness CLI를 실행한다.

`web`

Harness Web UI 환경을 실행한다.

`--no-open`

현재 환경은 Desktop Browser가 없는 Linux VM이므로 Browser 자동 실행을 비활성화한다.

---

정상적으로 실행되면 Harness Web은 VM 내부에서 다음 주소를 사용한다.

```text
127.0.0.1:3080
```

이 Terminal을 종료하면 foreground에서 실행 중인 Harness Process도 종료될 수 있으므로 테스트 중에는 Terminal을 유지한다.

---

# 14. SSH Tunnel 구성

Harness의 3080 Port를 인터넷에 직접 공개하지 않고 SSH Tunnel을 사용한다.

Windows에서 새로운 Terminal을 열고:

```powershell
cd $HOME\Downloads
```

Tunnel 연결:

```powershell
ssh -i "deepseek-harness-t1.pem" -N -L 3080:127.0.0.1:3080 ubuntu@<EC2-Public-DNS>
```

### 핵심 옵션

`-N`

Remote Shell을 실행하지 않고 SSH 연결을 Tunnel 용도로만 유지한다.

`-L`

Local Port Forwarding을 설정한다.

```text
-L 3080:127.0.0.1:3080
```

의 의미:

```text
Windows
127.0.0.1:3080
      ↓
SSH Tunnel
      ↓
EC2
127.0.0.1:3080
      ↓
Harness
```

따라서 AWS Security Group에 3080을 외부 공개할 필요가 없다.

---

Windows Browser에서 다음 주소로 접속한다.

```text
http://127.0.0.1:3080
```

Harness Web UI가 정상적으로 표시되는 것을 확인하였다.

---

# 15. LLM / Tool Call 검증

Harness Web UI에서 실제 요청을 수행하였다.

```text
파일구조 읽어봐
```

Harness는 단순히 Text Response만 반환하지 않고 Bash Tool을 호출하였다.

실행 흐름:

```text
User Message
    ↓
LLM 판단
    ↓
Tool Call
    ↓
Bash 실행
    ↓
Tool Result
    ↓
다음 LLM Step
    ↓
추가 Tool Call
    ↓
최종 Assistant Response
```

실제 화면에서는:

```text
1 Turn
5 Steps
```

가 수행되는 것을 확인하였다.

---

Bash Tool에서는 다음과 같은 Command가 사용되었다.

```bash
pwd
```

현재 작업 Directory를 출력한다.

```bash
ls
```

현재 Directory 내부의 파일 및 Folder를 출력한다.

이를 통해 Harness가 실제 EC2의:

```text
/home/ubuntu/deepseek-harness
```

Workspace에 접근하고 명령을 실행하는 것을 확인하였다.

---

# 16. T11 비교용 Baseline 측정

Tool Call을 포함한 단일 사용자 요청 실행 이후 Resource 상태를 측정하였다.

## 16.1 System Load

```bash
uptime
```

### 의미

VM이 얼마나 오래 실행되었는지와 Load Average를 표시한다.

실제 결과:

```text
up 41 min
load average: 0.00, 0.03, 0.06
```

Load Average는 각각 최근:

```text
1분
5분
15분
```

동안 System의 평균적인 작업 부하를 나타낸다.

---

## 16.2 Memory

```bash
free -h
```

결과:

```text
Total RAM:     3.7 GiB
Used RAM:      1.0 GiB
Available RAM: 2.7 GiB

Swap Total:    4.0 GiB
Swap Used:     4.7 MiB
```

---

## 16.3 Node Process

```bash
ps -eo pid,%cpu,%mem,rss,cmd --sort=-rss | grep node | grep -v grep
```

### 의미

`ps`

현재 실행 중인 Process를 확인한다.

`-e`

모든 Process를 표시한다.

`-o`

표시할 Column을 지정한다.

```text
pid   Process ID
%cpu  CPU 사용률
%mem  Memory 사용 비율
rss   실제 RAM 점유량
cmd   실행 Command
```

`--sort=-rss`

Memory RSS가 큰 Process부터 정렬한다.

`grep node`

Node.js Process만 필터링한다.

`grep -v grep`

검색 과정에서 실행된 grep Process 자체는 결과에서 제외한다.

---

실제 Harness Process:

```text
node --import tsx/esm apps/cli/src/bin.ts web --no-open
```

측정값:

```text
CPU: 0.9%
Memory: 13.2%
RSS: 519348 KiB
```

RSS를 환산하면 약:

```text
507 MiB
```

이다.

---

# 17. Disk 사용량 측정

```bash
df -h /
```

### 의미

`df`

File System의 Disk 사용량을 확인한다.

`-h`

GiB / MiB 등 사람이 읽기 쉬운 단위로 출력한다.

`/`

Root File System만 확인한다.

---

실제 결과:

```text
Disk Total: 29 GiB
Used:       8.9 GiB
Available:  20 GiB
Usage:      32%
```

---

# 18. T1 검증 결과

| 검증 항목 | 결과 |
|---|---|
| AWS EC2 생성 | PASS |
| Ubuntu SSH 접속 | PASS |
| Node.js 설치 | PASS |
| pnpm 설치 | PASS |
| Dependency 설치 | PASS |
| Source Build | PASS |
| Harness Web 실행 | PASS |
| SSH Tunnel 접속 | PASS |
| Web UI 원격 접속 | PASS |
| LLM Response | PASS |
| Tool Call | PASS |
| Tool Result | PASS |
| VM Workspace 접근 | PASS |
| Resource Baseline 측정 | PASS |

최종 결과:

```text
T1 VM Deployment = PASS
```

---

# 19. Single-User Baseline

이번 측정은 완전한 Idle 상태가 아니다.

Harness에서 단일 사용자가 Tool Call을 포함한 요청을 수행한 뒤 Harness가 계속 실행 중인 상태에서 측정하였다.

따라서 다음과 같이 정의한다.

```text
Single-User Steady-State Baseline
```

| 항목 | 결과 |
|---|---:|
| Load Average | 0.00 / 0.03 / 0.06 |
| RAM Used | 약 1.0 GiB |
| RAM Available | 약 2.7 GiB |
| Swap Used | 약 4.7 MiB |
| Harness Node RSS | 약 507 MiB |
| Harness Node CPU | 약 0.9% |
| Disk Usage | 8.9 / 29 GiB |
| Disk Usage Rate | 32% |

이 값은 이후 T11 동시 사용자 테스트와 비교하기 위한 Baseline으로 사용한다.

---

# 20. T1에서 확인한 사항

1. DeepSeek Harness는 AWS EC2 Ubuntu VM에서 Source Build 방식으로 정상 실행할 수 있다.

2. Harness Web UI의 3080 Port를 인터넷에 직접 공개하지 않고 SSH Tunnel을 통해 접근할 수 있다.

3. Harness는 VM 환경에서도 LLM Response뿐 아니라 실제 Tool Call과 Tool Result를 처리할 수 있다.

4. Bash Tool을 통해 EC2 Workspace에 실제 접근하고 Command를 실행할 수 있다.

5. 약 2 GiB RAM의 `t3.small`에서도 Dependency 설치는 가능했지만 Source Build 과정에서는 Swap 의존으로 인해 성능 저하가 크게 발생했다.

6. 이번 T1에서는 `t3.medium`이 Build 및 기본 실행 검증에 더 적합했다.

7. Single-User 상태에서 Harness Main Node Process는 약 507 MiB RSS를 사용하였다.

8. 이번 Baseline은 다음 단계인 T11 동시 사용자 부하 테스트의 비교 기준으로 사용할 수 있다.

---

# 21. 주요 명령어 요약

| 표현 | 의미 |
|---|---|
| `sudo` | 관리자 권한으로 실행 |
| `~` | 현재 Linux 사용자의 Home Directory |
| `$HOME` | 현재 사용자의 Home Directory |
| `\|` | 앞 명령 출력을 뒤 명령 입력으로 전달 |
| `-y` | 설치 질문에 자동 Yes |
| `-h` | 사람이 읽기 쉬운 단위로 출력 |
| `-g` | npm Package Global 설치 |
| `-p` | 필요한 상위 Directory까지 생성 |
| `-N` | SSH를 Tunnel 용도로만 사용 |
| `-L` | SSH Local Port Forwarding |
| `$?` | 직전 명령의 Exit Code |

---

# 22. 다음 단계

현재 진행 상태:

```text
T1 VM 배포                 완료
T11 동시 사용자 부하 테스트  예정
T2 규모 테스트              예정
```

다음 단계는 T11이다.

T11에서는 여러 개의 독립 Session / Workspace를 사용해 요청을 동시에 발생시키고 다음 지표를 측정한다.

```text
Concurrent Users
Latency
Success Rate
Failure Rate
CPU
Memory
Throughput
Error
```

DeepSeek Harness에 존재하는 Browser Stress Test는 많은 Reasoning Chunk를 Browser에서 처리하는 Renderer Stress Test에 가깝다.

따라서 T11에서 필요한 **동시 사용자 부하 테스트는 별도의 Test Code로 구성해야 한다.**
