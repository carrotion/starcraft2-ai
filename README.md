# StarCraft 2 AI (`starcraft2-ai`)
### Coached Terran Bot & Multi-Process Autonomous Learning Suite

스타크래프트 II(StarCraft II) 및 스타크래프트 I(Brood War)을 위한 하이브리드 코치형 AI 에이전트 및 강화학습·대시보드 모니터링 시스템입니다.

---

## 1. 프로젝트 주요 특징 (StarCraft II)

### 1) 지능형 코치드 테란 봇 (`CoachedTerranBot`)
- **안전한 입구/언덕 심시티**: 램프 쵸크(입구)의 정밀 3x3 벙커 및 보급고 락 배치, 병력 진출로 확보(미들 라인 비움)
- **스마트 게이트 (Smart Gate)**: 평시에는 보급고를 내려 병력 동선을 유지하고, 적 접근 시 자동 상승 방어
- **자원 및 전황 기반 유동적 멀티 확장 (Dynamic Multi-Base)**:
  - 2기지(앞마당): 본진 벙커 + 해병 확보 시 빠른 확장
  - 3기지(삼룡이): 앞마당 활성화, 전차/바이오닉 병력 수비력 확보, 또는 자원 고갈 시 확장
  - 4기지+(후반 매크로): 잉여 자원 누적 및 후반 자원 마름에 따라 지속적인 추가 기지 확보
  - 기지 수에 따른 일꾼 최적 상한(최대 70기) 및 궤도 사령부(지게로봇/스캔) 자동 관리
- **전술적 마이크로 컨트롤 (`MicroController`)**:
  - 바이오닉(해병+불곰): 스팀팩 가속, 적 근접 유닛 상대 거리 유지(Kiting), 은폐 유닛 감지 및 대응
  - 공성 전차(Siege Tank): 최전선 거점 방어 시즈 모드 전환, 전선 진격 시 순차적 전진 배치
  - 의료선(Medivac): 후방 안전 비행 및 부상 바이오닉 치유

### 2) 웹 관제 대시보드 & 실시간 중계 레이더
- **실시간 웹 대시보드**: FastAPI + TailwindCSS 기반 브라우저 관제 시스템 (`http://127.0.0.1:8000`)
- **실시간 택티컬 레이더 (Canvas Radar)**:
  - 아군 기지, 벙커 거점, 바이오닉/전차, 적 부대 위치를 60FPS 실시간 시각화
  - 맵 크기에 따른 자동 뷰포트 스케일링
- **멀티 워커 실시간 전환 탭**: 1~8개 병렬 프로세스 중 원하는 워커 화면을 원클릭으로 선택하여 실시간 관전
- **AI 캐스터 해설 피드**: 기지 확장, 교전 개시, 테크 업그레이드 등 주요 이벤트를 텍스트로 실시간 브로드캐스팅

### 3) 래더 대형 맵 풀 & 자율 전략 진화기
- **다양한 래더 맵 로테이션**:
  - `Simple128`, `AcropolisLE`, `CatalystLE`, `AcidPlantLE`, `ThunderbirdLE`, `TritonLE` 등 대형 래더 맵 지원
- **자율 전략 적응기 (`AutonomousEvaluator`)**:
  - 경기 결과(승/패)와 플레이 시간을 분석하여 목표 병영 수, 생산 주기, 진격 타이밍, 최대 기지 수 자동 최적화

---

## 2. 디렉토리 구조

```
starcraft/
├── config.yaml             # 환경 및 하이퍼파라미터 설정
├── requirements.txt        # Python 패키지 의존성
├── dashboard_server.py     # FastAPI 웹 관제 및 중계 서버
├── run_dashboard.bat       # 대시보드 일반 실행 배치
├── run_dashboard_admin.bat # 대시보드 관리자 권한 자동 승격 실행기
├── train_sc2.py            # SC2 멀티프로세스 자율 학습 및 경기 진행기
├── run_sc2.py              # SC2 단일 경기 실행 및 테스트 스크립트
├── templates/
│   └── index.html          # 웹 대시보드 프론트엔드 (레이더, 실시간 중계, 통계)
├── src/
│   ├── sc2_bot/
│   │   ├── coached_bot.py      # 코치형 테란 봇 메인 AI 엔진
│   │   ├── micro_controller.py # 유닛별 정밀 마이크로 컨트롤러
│   │   └── strategy_guide.py   # 전략 설정 및 빌드오더 가이드북
│   ├── sc2_learning/
│   │   ├── evaluator.py        # 경기 평가 및 자율 전략 진화기
│   │   ├── live_telemetry.py   # 대시보드 연동 실시간 텔레메트리 송출기
│   │   └── process_manager.py  # 대시보드 백그라운드 학습 프로세스 관리자
│   ├── envs/                   # SC1 강화학습 환경 (Gymnasium)
│   ├── agents/                 # PPO 강화학습 에이전트
│   └── utils/                  # 화면 캡처, DirectInput 제어 등
└── learning_stats/             # 경기 기록 및 텔레메트리 저장소
```

---

## 3. 시작하기 (Quick Start)

### 1) 환경 준비
```powershell
# 가상환경 활성화 (Python 3.12 권장)
.venv\Scripts\activate

# 패키지 설치
pip install -r requirements.txt
```

### 2) 웹 관제 대시보드 실행
```powershell
# 관리자 권한으로 실행 (권장)
.\run_dashboard_admin.bat

# 또는 직접 실행
python dashboard_server.py
```
브라우저에서 `http://127.0.0.1:8000` 접속 후 워커 수(1~8), 상대 종족, 난이도를 선택하고 **"학습 시작"**을 클릭합니다.

### 3) 콘솔 직접 실행
```powershell
# 4개 프로세스 병렬 래더 경기 진행
python train_sc2.py --workers 4 --difficulty VeryHard --races random

# 단일 경기 디버깅 실행 (그래픽 표시)
python run_sc2.py --map AcropolisLE --difficulty VeryHard
```

---

## 4. 라이선스

이 프로젝트는 개인 연구 및 학습 목적으로 제작되었습니다.
StarCraft 및 StarCraft II의 모든 권리는 Blizzard Entertainment에 있습니다.
