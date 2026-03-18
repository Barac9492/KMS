# Korea Mania Signal (KMS) — PRD v1.0

> 개인용 한국 테마 ETF 모멘텀 트레이딩 시스템  
> Claude Code 구현 기준 문서

---

## 1. 개요

### 핵심 가설
한국 소비 열풍(마라톤, AI, 2차전지 등)은 주식 시장에 **시차를 두고** 반영된다.  
대중의 소셜/검색 관심 급등이 관련 테마 ETF 가격보다 **2~4주 선행**한다는 가설을 백테스팅으로 검증하고, 검증된 신호를 기반으로 중기(1~4주) 매매 신호를 자동 생성한다.

### 사용자
Ethan (1인 개인 투자자). 매일 직접 시장을 보지 않아도, 시스템이 매주 1회 신호를 생성해주면 된다.

### 기대 산출물
- 매주 월요일 아침, 터미널에서 `python run.py` 실행 → 이번 주 매매 신호 출력
- 과거 백테스팅 결과 리포트 (HTML 또는 터미널 출력)

---

## 2. 시스템 구조

```
KMS/
├── run.py                  # 진입점. 주간 신호 생성 실행
├── backtest.py             # 백테스팅 실행
├── config.py               # ETF 목록, 파라미터, API 키 설정
├── data/
│   ├── fetch_etf.py        # ETF 가격/거래량 수집 (FinanceDataReader + pykrx)
│   └── fetch_trend.py      # 네이버 DataLab 검색트렌드 수집
├── signals/
│   ├── search_signal.py    # 레이어 1: 검색 신호
│   ├── volume_signal.py    # 레이어 3: 거래량 신호
│   └── signal_combiner.py  # 3개 레이어 통합 → 최종 신호
├── backtest/
│   ├── engine.py           # 백테스팅 루프
│   └── metrics.py          # 성과 지표 계산
├── report/
│   └── reporter.py         # 결과 출력 (터미널 + HTML)
└── requirements.txt
```

---

## 3. 타겟 ETF 유니버스

`config.py`에 딕셔너리로 관리. 추가/삭제 가능하도록 설계.

```python
ETF_UNIVERSE = {
    "2차전지": [
        {"name": "TIGER 2차전지테마", "code": "305540"},
        {"name": "KODEX 2차전지산업", "code": "305720"},
    ],
    "AI반도체": [
        {"name": "KODEX AI반도체핵심장비", "code": "396500"},
        {"name": "TIGER AI코리아그로스액티브", "code": "448290"},
    ],
    "방산": [
        {"name": "TIGER 방산산업", "code": "457480"},
        {"name": "KODEX K-방산우주", "code": "494670"},
    ],
    "바이오": [
        {"name": "TIGER 헬스케어", "code": "143860"},
        {"name": "KODEX 바이오", "code": "244580"},
    ],
    "로봇": [
        {"name": "KODEX K-로봇액티브", "code": "441680"},
    ],
}
```

---

## 4. 데이터 수집

### 4-1. ETF 가격/거래량 (`data/fetch_etf.py`)

**라이브러리:** `FinanceDataReader`, `pykrx`

```
pip install finance-datareader pykrx
```

**수집 항목:**
- 일별 종가 (수정주가)
- 일별 거래량
- 20일 이동평균 (종가 기준)
- 20일 평균 거래량

**구현 방식:**
```python
import FinanceDataReader as fdr
from pykrx import stock

def fetch_etf_data(code: str, start: str, end: str) -> pd.DataFrame:
    df = fdr.DataReader(code, start, end)
    df['MA20'] = df['Close'].rolling(20).mean()
    df['VolMA20'] = df['Volume'].rolling(20).mean()
    df['VolRatio'] = df['Volume'] / df['VolMA20']
    return df
```

**데이터 기간:** 2019-01-01 ~ 현재 (백테스팅용)

---

### 4-2. 네이버 DataLab 검색트렌드 (`data/fetch_trend.py`)

**API:** 네이버 DataLab 검색트렌드 API  
**공식 문서:** https://developers.naver.com/docs/serviceapi/datalab/search/v1/

**사전 준비 (사용자가 직접):**
1. https://developers.naver.com 에서 애플리케이션 등록
2. "데이터랩(검색트렌드)" 권한 추가
3. Client ID, Client Secret 발급
4. `config.py`의 `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`에 입력

**API 스펙:**
- URL: `https://openapi.naver.com/v1/datalab/search`
- Method: POST
- 반환: 최근 1년간 주간 상대 검색량 (0~100)

**수집 항목 (테마별 키워드 매핑):**

```python
TREND_KEYWORDS = {
    "2차전지": ["2차전지", "전기차 배터리", "에코프로"],
    "AI반도체": ["AI 반도체", "HBM", "엔비디아"],
    "방산": ["방산주", "한화에어로스페이스", "K방산"],
    "바이오": ["바이오주", "신약 개발", "임상시험"],
    "로봇": ["협동로봇", "로봇주", "레인보우로보틱스"],
}
```

**구현 방식:**
```python
import requests

def fetch_naver_trend(keywords: list, start_date: str, end_date: str) -> pd.DataFrame:
    """
    keywords: 최대 5개 키워드 리스트
    start_date, end_date: "YYYY-MM-DD" 형식
    반환: 날짜별 검색량 지수 (0~100)
    """
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
        "Content-Type": "application/json",
    }
    body = {
        "startDate": start_date,
        "endDate": end_date,
        "timeUnit": "week",
        "keywordGroups": [{"groupName": "target", "keywords": keywords}],
    }
    response = requests.post(
        "https://openapi.naver.com/v1/datalab/search",
        headers=headers,
        json=body,
    )
    # 파싱해서 DataFrame 반환
    ...
```

**주의:** DataLab API는 최대 1년치 데이터만 제공. 백테스팅용으로 과거 데이터를 쌓으려면 주기적으로 수집해서 로컬 CSV에 저장해야 함.  
→ `data/trend_cache/` 폴더에 테마별 CSV로 저장하는 캐싱 로직 필요.

---

## 5. 신호 로직

### 5-1. 레이어 1: 검색 신호 (`signals/search_signal.py`)

**계산:**
```
search_ratio = 최근 2주 평균 검색량 / 직전 6주 평균 검색량
```

**신호 ON 조건:** `search_ratio >= 1.8` (임계값. 백테스팅으로 최적화)  
**신호 방향:** "올라가는 중"일 때만 ON. 이미 최고점이면 OFF.  
→ `search_ratio`가 전주 대비 상승 중일 것 (피크 진입 방지)

**반환값:** 테마별 `{"signal": True/False, "ratio": float, "trend": "rising"/"falling"}`

---

### 5-2. 레이어 2: 언론 신호 (선택 구현 — P1)

빅카인즈 API (https://www.bigkinds.or.kr) 기반.  
MVP에서는 생략. 레이어 1 + 레이어 3만으로 먼저 백테스팅.

---

### 5-3. 레이어 3: 거래량 신호 (`signals/volume_signal.py`)

**계산:**
```
vol_ratio = 오늘 거래량 / 20일 평균 거래량
```

**신호 ON 조건:** `vol_ratio >= 1.5`  
**추가 조건:** 종가가 20일 이동평균 위에 있을 것 (`Close > MA20`)

**반환값:** ETF별 `{"signal": True/False, "vol_ratio": float, "above_ma20": bool}`

---

### 5-4. 최종 신호 통합 (`signals/signal_combiner.py`)

**진입 신호 (AND 조건):**
1. 레이어 1 ON (해당 테마 검색 신호)
2. 레이어 3 ON (해당 테마 대표 ETF 거래량 신호)

**청산 신호 (OR 조건 중 하나라도):**
1. 보유 4주 경과 (시간 청산)
2. 검색 신호 피크 대비 30% 하락 (`current_ratio < peak_ratio * 0.7`)
3. ETF 종가가 진입가 대비 -7% 이하 (손절)

**출력 포맷:**
```
[2026-03-18] 매매 신호 리포트
─────────────────────────────
테마: AI반도체
ETF:  KODEX AI반도체핵심장비 (396500)
신호: BUY
근거: 검색비율 2.3x (↑상승중) / 거래량비율 1.8x / MA20 위
─────────────────────────────
테마: 방산
ETF:  TIGER 방산산업 (457480)
신호: HOLD (진입 7일차, 현재 +4.2%)
청산 조건까지: 검색 피크 -12% / 손절까지 -2.8% 여유
─────────────────────────────
테마: 2차전지
신호: WATCH (검색 신호 1.4x — 임계값 미달)
```

---

## 6. 백테스팅 엔진

### 6-1. 엔진 (`backtest/engine.py`)

**기간:** 2019-01-01 ~ 2024-12-31  
**초기 자본:** 10,000,000원 (설정 가능)  
**포지션:** 신호 발생 시 자본의 20% 투입 (최대 5개 테마 동시 보유)  
**비용:** 매매 시마다 슬리피지 0.3% + 거래세 0.23% 반영

**루프 구조:**
```python
for date in trading_dates:
    # 1. 신호 계산 (해당 날짜 기준 과거 데이터만 사용 — look-ahead bias 금지)
    signals = compute_signals(data_up_to=date)
    
    # 2. 진입 처리
    for signal in signals:
        if signal.is_buy and not already_holding(signal.etf):
            enter_position(signal.etf, date, capital * 0.2)
    
    # 3. 청산 처리
    for position in open_positions:
        if should_exit(position, date, signals):
            exit_position(position, date)
    
    # 4. 포트폴리오 가치 기록
    record_portfolio_value(date)
```

**Look-ahead bias 방지 원칙:**  
신호 계산 시 항상 `data_up_to=date` 파라미터로 미래 데이터 차단. 이 원칙이 지켜지지 않으면 백테스팅 결과를 신뢰할 수 없음.

---

### 6-2. 성과 지표 (`backtest/metrics.py`)

계산 항목:
- **총 수익률** (%)
- **연환산 수익률 CAGR** (%)
- **최대 낙폭 MDD** (%)
- **승률** = 수익 거래 수 / 전체 거래 수
- **평균 보유 기간** (거래일)
- **샤프 비율** (무위험 수익률 3.5% 기준)
- **벤치마크 대비 초과수익** (KOSPI 200 ETF 비교)

---

### 6-3. 파라미터 최적화

백테스팅 시 다음 파라미터를 그리드 서치로 최적화:

```python
PARAM_GRID = {
    "search_threshold": [1.5, 1.8, 2.0, 2.5],   # 검색 신호 임계값
    "vol_threshold":    [1.3, 1.5, 2.0],           # 거래량 신호 임계값
    "stop_loss":        [0.05, 0.07, 0.10],         # 손절 비율
    "max_hold_weeks":   [2, 4, 6],                  # 최대 보유 기간
    "search_lookback":  [4, 6, 8],                  # 검색 기준 기간(주)
}
```

**주의:** 파라미터 최적화 후 동일 데이터로 검증하면 과적합(overfitting). 반드시 **Walk-forward validation** 적용:
- Train: 2019~2022
- Test: 2023~2024
- 테스트 기간 성과가 훈련 기간과 크게 다르면 전략 기각

---

## 7. 리포트 출력 (`report/reporter.py`)

### 터미널 출력 (매주 `run.py` 실행 시)
```
오늘의 KMS 신호 — 2026-03-18
══════════════════════════════
✅ BUY    AI반도체  KODEX AI반도체핵심장비 (396500)  검색 2.3x / 거래량 1.8x
⏳ HOLD   방산      TIGER 방산산업 (457480)           진입 7일 / +4.2%
👀 WATCH  2차전지   신호 임계값 미달 (1.4x)
❌ 없음   바이오    신호 없음
══════════════════════════════
```

### 백테스팅 HTML 리포트 (`backtest.py` 실행 시)
`report/backtest_result.html` 생성.  
포함 내용:
- 누적 수익률 차트 (vs KOSPI 200 벤치마크)
- 연도별 수익률 바 차트
- MDD 구간 표시 차트
- 거래 내역 테이블 (진입일, 청산일, 수익률, 청산 이유)
- 파라미터별 성과 히트맵

차트 라이브러리: `plotly` (인터랙티브)

---

## 8. 설치 및 실행

### 설치
```bash
git clone [repo]
cd KMS
pip install -r requirements.txt
```

**requirements.txt:**
```
finance-datareader
pykrx
pandas
numpy
requests
plotly
```

### API 키 설정
`config.py` 파일에 직접 입력:
```python
NAVER_CLIENT_ID = "여기에_입력"
NAVER_CLIENT_SECRET = "여기에_입력"
```

### 초기 데이터 수집 (처음 한 번만)
```bash
python data/fetch_trend.py --init  # 과거 트렌드 데이터 캐싱
```

### 주간 신호 확인 (매주 월요일)
```bash
python run.py
```

### 백테스팅 실행
```bash
python backtest.py
# → report/backtest_result.html 생성
```

---

## 9. 구현 우선순위

| 우선순위 | 기능 | 설명 |
|---------|------|------|
| P0 | ETF 데이터 수집 | FinanceDataReader + pykrx |
| P0 | 거래량 신호 (레이어 3) | 가장 단순. 먼저 검증 |
| P0 | 백테스팅 엔진 기본 루프 | 거래량 신호만으로 먼저 돌려보기 |
| P0 | 성과 지표 계산 | 총수익률, MDD, 승률 |
| P1 | 네이버 DataLab 연동 | API 키 발급 필요 |
| P1 | 검색 신호 (레이어 1) | DataLab 연동 후 추가 |
| P1 | 신호 통합 + 최종 판단 | 두 레이어 합치기 |
| P1 | 터미널 신호 출력 | run.py |
| P2 | HTML 리포트 | plotly 차트 |
| P2 | 파라미터 그리드 서치 | 최적화 |
| P2 | Walk-forward validation | 과적합 방지 검증 |

---

## 10. 핵심 제약사항 및 주의사항

1. **Look-ahead bias 절대 금지**: 백테스팅에서 미래 데이터를 참조하면 결과가 무의미. `data_up_to` 파라미터 반드시 적용.

2. **네이버 DataLab 과거 데이터 한계**: API가 최대 1년치만 제공. 2019년부터의 백테스팅을 위해서는 직접 수집해서 쌓은 캐시 데이터가 필요. 구현 초기에는 2023년 이후 데이터로만 백테스팅 가능.

3. **ETF 슬리피지 반영 필수**: 소형 테마 ETF는 스프레드가 크다. 이론 수익에서 0.3~0.5% 차감 없이 나온 결과는 신뢰 불가.

4. **신호 ≠ 매매 지시**: 이 시스템은 신호를 생성할 뿐, 실제 매수/매도는 사용자가 직접 판단. 자동주문 연결은 충분한 실전 검증 이후 별도 단계로 진행.

5. **pykrx 호출 빈도 제한**: 과도한 API 호출 시 차단될 수 있음. 수집한 데이터는 로컬 CSV에 캐싱해서 재사용.

---

## 11. 향후 확장 (v2.0)

- 한국투자증권 Open API 연결 → 신호 발생 시 자동 주문
- 빅카인즈 API 추가 → 레이어 2 (언론 신호) 구현
- Slack/카카오 알림 → 신호 발생 시 푸시
- 텔레그램 봇 → 어디서든 `run.py` 결과 확인

---

*KMS PRD v1.0 | 2026-03-18*
