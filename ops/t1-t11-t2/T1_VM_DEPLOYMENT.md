# T1 - DeepSeek Harness VM Deployment

## 1. 목적

T1의 목적은 DeepSeek Harness를 로컬 PC가 아닌 별도의 Linux VM 환경에 배포하고,
원격 환경에서도 Harness Runtime과 Web UI가 정상적으로 동작하는지 확인하는 것이다.

이번 단계에서는 성능 최적화나 다중 사용자 처리를 진행하지 않는다.

우선 다음 흐름이 정상 동작하는 것을 목표로 한다.

```text
Local PC
   │
   │ SSH Tunnel
   ▼
Linux VM
   │
   ├─ DeepSeek Harness
   ├─ Agent Loop
   ├─ Tool Runtime
   └─ Web UI : 127.0.0.1:3080
```

T1 완료 후 동일 VM 환경을 기준으로 T11 동시 사용자 부하 테스트를 진행한다.

---

## 2. 테스트 환경

### 권장 VM 환경

T1 초기 배포 검증을 위한 기준 환경이다.

| 항목 | 기준 |
|---|---|
| OS | Ubuntu 24.04 LTS |
| CPU | 4 vCPU |
| Memory | 8 GB RAM |
| Storage | 30 GB 이상 |
| Architecture | x86_64 |
| Node.js | 24.x |
| pnpm | 11.7.0 |

위 사양은 DeepSeek Harness의 공식 최소 요구 사양이 아니라
소스 Build 및 이후 부하 테스트를 안정적으로 수행하기 위한 초기 테스트 환경이다.

### 네트워크

VM Firewall 또는 Cloud Security Group에서는 우선 SSH만 허용한다.

```text
TCP 22
Source: 테스트를 수행하는 PC의 IP
```

Harness Web UI의 기본 포트인 `3080`은 외부 인터넷에 직접 노출하지 않는다.

T1에서는 SSH Port Forwarding을 이용하여 접근한다.

---

## 3. VM 접속

AWS EC2를 사용하는 경우 예시는 다음과 같다.

```bash
ssh -i <PRIVATE_KEY.pem> ubuntu@<VM_PUBLIC_IP>
```

일반적인 Linux VM은 다음과 같이 접속한다.

```bash
ssh <USER>@<VM_PUBLIC_IP>
```

접속 후 OS 정보를 확인한다.

```bash
uname -a
cat /etc/os-release
```

---

## 4. 기본 패키지 설치

패키지 목록을 갱신한다.

```bash
sudo apt update
```

필요한 기본 패키지를 설치한다.

```bash
sudo apt install -y \
  git \
  curl \
  ca-certificates \
  build-essential \
  python3
```

설치 여부를 확인한다.

```bash
git --version
python3 --version
gcc --version
```

---

## 5. Node.js 24 설치

DeepSeek Harness의 현재 repository는 다음 Node.js 버전을 요구한다.

```text
^22.19.0 || >=24.0.0
```

T1 테스트에서는 Node.js 24를 사용한다.

NodeSource repository를 등록한다.

```bash
curl -fsSL https://deb.nodesource.com/setup_24.x | sudo -E bash -
```

Node.js를 설치한다.

```bash
sudo apt install -y nodejs
```

버전을 확인한다.

```bash
node --version
npm --version
```

예상 결과:

```text
v24.x.x
```

---

## 6. pnpm 설치

프로젝트의 현재 `package.json`은 pnpm 11.7.0을 사용한다.

```bash
sudo npm install -g pnpm@11.7.0
```

확인:

```bash
pnpm --version
```

예상 결과:

```text
11.7.0
```

---

## 7. DeepSeek Harness Repository Clone

T1 / T11 / T2 작업용 branch를 clone한다.

```bash
cd ~
```

```bash
git clone \
  -b feature/t1-t11-t2-validation \
  --single-branch \
  https://github.com/Text-To-SQL-Agent/deepseek-harness.git
```

Repository로 이동한다.

```bash
cd deepseek-harness
```

현재 branch를 확인한다.

```bash
git branch --show-current
```

예상 결과:

```text
feature/t1-t11-t2-validation
```

현재 commit도 기록한다.

```bash
git rev-parse HEAD
```

T1 결과를 정리할 때 동일 commit 기준으로 테스트했는지 확인하기 위해 사용한다.

---

## 8. Dependency 설치

Repository root에서 실행한다.

```bash
pnpm install --frozen-lockfile
```

정상적으로 완료되면 다음 단계로 진행한다.

---

## 9. Source Build

DeepSeek Harness 실행에 필요한 Host, Client 및 Web artifact를 생성한다.

```bash
pnpm run build
```

Build가 성공하면 다음 명령으로 현재 환경을 기록한다.

```bash
node --version
pnpm --version
git rev-parse --short HEAD
```

---

## 10. Harness Home 분리

T1 테스트용 Harness 설정과 Session을 별도로 관리하기 위해
전용 `DSH_HOME`을 사용한다.

```bash
mkdir -p "$HOME/dsh-t1-home"
```

```bash
export DSH_HOME="$HOME/dsh-t1-home"
```

확인:

```bash
echo "$DSH_HOME"
```

예상 결과:

```text
/home/ubuntu/dsh-t1-home
```

사용자 이름에 따라 실제 경로는 달라질 수 있다.

---

## 11. Web UI 실행

먼저 foreground에서 Harness가 정상 실행되는지 확인한다.

Repository root에서 실행한다.

```bash
pnpm dsh web --no-open
```

정상 실행 시 Web UI는 기본적으로 다음 주소에서 동작한다.

```text
http://127.0.0.1:3080
```

VM에서는 GUI Browser를 사용할 필요가 없기 때문에 `--no-open` 옵션을 사용한다.

---

## 12. VM 내부 동작 확인

다른 SSH terminal에서 VM에 접속한 뒤 확인한다.

### Port 확인

```bash
ss -ltn | grep 3080
```

정상적인 경우 `127.0.0.1:3080`에서 LISTEN 상태를 확인할 수 있다.

### HTTP 확인

```bash
curl -I http://127.0.0.1:3080
```

HTTP 응답이 반환되면 Web Server가 정상 실행 중인 것이다.

---

## 13. Background 실행

Foreground 동작을 확인한 이후 T1 테스트를 위해 background에서 실행할 수 있다.

기존 Harness를 `Ctrl + C`로 종료한 후 다음 명령을 사용한다.

```bash
cd ~/deepseek-harness
```

```bash
export DSH_HOME="$HOME/dsh-t1-home"
```

```bash
nohup pnpm dsh web --no-open \
  > "$HOME/deepseek-harness-t1.log" 2>&1 &
```

실행 PID를 저장한다.

```bash
echo $! > "$HOME/deepseek-harness-t1.pid"
```

확인:

```bash
cat "$HOME/deepseek-harness-t1.pid"
```

로그 확인:

```bash
tail -f "$HOME/deepseek-harness-t1.log"
```

---

## 14. Local PC에서 SSH Tunnel 연결

Harness Web UI는 VM의 `127.0.0.1:3080`에서 실행되므로
로컬 PC에서 SSH Port Forwarding을 사용한다.

### SSH Key를 사용하는 경우

로컬 PC에서 실행한다.

```bash
ssh -i <PRIVATE_KEY.pem> \
  -L 3080:127.0.0.1:3080 \
  ubuntu@<VM_PUBLIC_IP>
```

### 일반 SSH 접속

```bash
ssh \
  -L 3080:127.0.0.1:3080 \
  <USER>@<VM_PUBLIC_IP>
```

SSH 연결을 유지한 상태에서 로컬 Browser를 실행한다.

```text
http://127.0.0.1:3080
```

다음 화면이 정상적으로 표시되는지 확인한다.

```text
DeepSeek Harness Web UI
```

---

## 15. Model Provider 설정

Web UI에서 기존 로컬 개발 환경과 동일한 Model Provider를 설정한다.

```text
Settings
→ Models
→ Provider 설정
→ Model 선택
```

API Key는 Repository에 저장하거나 commit하지 않는다.

`.env`, source code, Markdown 문서 등에 실제 API Key를 작성하지 않는다.

---

## 16. 기본 Agent 동작 확인

새 Session을 생성한 뒤 간단한 요청을 전송한다.

예:

```text
Say hello and briefly explain what workspace you can access.
```

다음 항목을 확인한다.

```text
User Message
↓
LLM Request
↓
Assistant Response
↓
Session 기록
```

Workspace Tool이 활성화되어 있다면 간단한 파일 조회 요청도 수행한다.

예:

```text
List the files in the current workspace.
```

Tool Call과 Tool Result가 정상적으로 기록되는지 확인한다.

---

## 17. VM Resource 확인

Harness가 실행 중인 상태에서 기본 Resource 사용량을 기록한다.

### CPU / Process

```bash
top
```

또는 Node process만 확인한다.

```bash
ps -eo pid,%cpu,%mem,rss,cmd \
  | grep node \
  | grep -v grep
```

### Memory

```bash
free -h
```

### Disk

```bash
df -h
```

T11에서 동시 사용자 수가 증가했을 때의 값과 비교하기 위해
T1의 idle / single request 값을 baseline으로 저장한다.

---

## 18. Harness 종료

Background Process를 종료할 때는 저장한 PID를 사용한다.

```bash
kill "$(cat "$HOME/deepseek-harness-t1.pid")"
```

Process 확인:

```bash
ps -p "$(cat "$HOME/deepseek-harness-t1.pid")"
```

Process가 존재하지 않으면 정상 종료된 것이다.

---

## 19. T1 완료 기준

다음 항목을 모두 만족하면 T1 VM Deployment를 완료한 것으로 판단한다.

- [ ] Ubuntu VM 생성
- [ ] Node.js 24 설치
- [ ] pnpm 11.7.0 설치
- [ ] `feature/t1-t11-t2-validation` branch clone
- [ ] `pnpm install --frozen-lockfile` 성공
- [ ] `pnpm run build` 성공
- [ ] `pnpm dsh web --no-open` 실행 성공
- [ ] VM 내부 `127.0.0.1:3080` HTTP 응답 확인
- [ ] SSH Tunnel을 통한 Local Browser 접속 성공
- [ ] Model Provider 연결 성공
- [ ] 일반 LLM 요청 성공
- [ ] Tool Call / Tool Result 정상 동작 확인
- [ ] VM CPU / Memory baseline 기록

---

## 20. 기록할 테스트 결과

T1 실행 후 아래 정보를 기록한다.

| 항목 | 결과 |
|---|---|
| Cloud / VM | |
| VM Instance Type | |
| vCPU | |
| RAM | |
| OS | |
| Node.js | |
| pnpm | |
| Git Commit SHA | |
| Build | PASS / FAIL |
| Web Server | PASS / FAIL |
| SSH Tunnel | PASS / FAIL |
| LLM Request | PASS / FAIL |
| Tool Call | PASS / FAIL |
| Idle Memory | |
| Single Request Memory | |
| Single Request CPU | |
| 비고 | |

---

## 21. T1 이후 진행

T1에서 검증한 동일한 VM 환경을 T11의 baseline으로 사용한다.

```text
T1
VM 배포
↓
Single Session 정상 동작 확인
↓
Baseline Resource 측정
↓

T11
Concurrent Session Load Test
↓
1 / 5 / 10 / 20 / 50 users
↓

T2
Workload / Data Scale Test
```

T11에서는 서로 다른 Session ID를 가진 요청을 동시에 실행하여
동시 사용자 증가에 따른 Latency, Success Rate, CPU, Memory 사용량을 측정한다.
