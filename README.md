# bison-bithumb-alert-bot

빗썸 KRW 마켓을 5분마다 훑어서 비손식 차트 조건에 가까운 종목을 텔레그램으로 알려주는 알림 도구입니다. GitHub Actions scheduled workflow로 돌릴 수 있어 PC를 켜둘 필요가 없습니다.

이 봇은 투자 조언, 투자 판단 대행, 자동매매 봇이 아닙니다. 빗썸 Public API와 Telegram Bot API만 사용하며, 주문/출금/Private API/빗썸 API 키 기능은 없습니다. 모든 알림의 최종 판단은 사용자 몫입니다.

## 1. 이 봇이 하는 일

- 빗썸 KRW 전체 종목을 `ALL_KRW`로 light scan합니다.
- 전수조사는 전체 종목의 현재가/24H 고가/24H 저가/거래대금/변화율만 보는 light scan입니다.
- deep scan은 거래대금 상위, light scan 후보, `always_include`, `manual_risk_symbols` 같은 후보 종목만 캔들 분석합니다.
- 무료 운영에서는 전종목 deep scan을 매 5분마다 하지 않습니다.
- 5분, 15분, 1시간 마감 캔들만 사용해 sweep, recovery, MSS, displacement, FVG, premium/discount, DOL을 계산합니다.
- `BUY_NOW_A/B/C`, `BID`, `CONFIRM`, `AVOID`로 분류합니다.
- 기본 설정에서는 `BUY_NOW_*`와 `BID`만 개별 텔레그램 알림으로 보냅니다.

## 2. 하지 않는 일

- 자동 매수/매도/주문을 하지 않습니다.
- 빗썸 API 키를 요구하지 않습니다.
- 빗썸 Private API, 주문 API, 출금 API 코드를 포함하지 않습니다.
- 알림은 차트 기반 참고 신호일 뿐이고 최종 판단은 사용자 몫입니다.

## 3. 로컬 실행 방법

Python 3.11 이상이 필요합니다.

```bash
python -m pip install -e ".[dev]"
python -m bison_bot.main --once --dry-run
```

빠른 로컬 테스트는 light/deep 범위를 제한하고 텔레그램 처리를 건너뜁니다.

```bash
python -m bison_bot.main --once --dry-run --max-symbols 30 --max-deep-symbols 10 --skip-telegram
```

시간 제한까지 걸고 확인하려면 다음처럼 실행합니다.

```bash
python -m bison_bot.main --once --dry-run --max-symbols 30 --max-deep-symbols 10 --skip-telegram --max-runtime-seconds 120
```

실제 텔레그램 전송은 `.env`에 토큰과 chat_id를 넣은 뒤 실행합니다.

```bash
python -m bison_bot.main --once
```

토큰이나 chat_id가 없으면 자동으로 콘솔 출력처럼 동작합니다.

## 4. Telegram BotFather로 토큰 만들기

1. 텔레그램에서 `@BotFather`를 찾습니다.
2. `/newbot`을 입력합니다.
3. 봇 이름과 username을 정합니다.
4. 발급된 token을 `.env`의 `TELEGRAM_BOT_TOKEN`에 넣습니다.

## 5. chat_id 얻는 방법

1. 만든 봇에게 아무 메시지나 보냅니다.
2. 아래 주소를 브라우저에서 엽니다.

```text
https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getUpdates
```

3. 응답에서 `chat.id` 값을 찾아 `.env`의 `TELEGRAM_CHAT_ID`에 넣습니다.

## 6. GitHub Secrets 설정

GitHub 저장소의 `Settings > Secrets and variables > Actions > New repository secret`에서 설정합니다.

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

`PORTFOLIO_YAML_BASE64`는 필수가 아닙니다. 기본 설정에서는 포트폴리오 기능이 꺼져 있습니다.

## 7. 포트폴리오 기능

기본값은 `config.yml`의 아래 설정입니다.

```yaml
portfolio:
  enabled: false
```

이 상태에서는 `portfolio.yml`을 읽지 않고, `PORTFOLIO_YAML_BASE64`도 읽지 않으며, 포트폴리오 기반 `HOLD`, `TAKE_PROFIT`, `CUT_REDUCE` 메시지도 보내지 않습니다.

나중에 직접 평단/수량 기반 관리를 쓰고 싶을 때만 `portfolio.enabled: true`로 바꾸고 `portfolio.example.yml`을 참고해 `portfolio.yml`을 만듭니다. `portfolio.yml`은 `.gitignore`에 포함되어 있으므로 public repo에 올리지 마세요.

`PORTFOLIO_YAML_BASE64`를 만들 때는 다음처럼 할 수 있습니다.

```bash
python -c "import base64, pathlib; print(base64.b64encode(pathlib.Path('portfolio.yml').read_bytes()).decode())"
```

## 8. GitHub Actions 5분 스케줄

`.github/workflows/scan.yml`은 아래 cron으로 실행됩니다.

```yaml
cron: "*/5 * * * *"
```

GitHub Actions는 초단위 실시간 봇이 아니라 5분 주기 알림 도구입니다. GitHub 지연, API 장애, rate limit이 있으면 해당 실행은 실패하거나 일부 종목을 건너뛰고 다음 실행에서 다시 시도합니다.

workflow는 동시 실행을 막기 위해 `concurrency`를 사용합니다. 기본 실행 명령은 4분 타임아웃 안에서 끝나도록 아래처럼 가볍게 둡니다.

```bash
python -m bison_bot.main --once --max-runtime-seconds 240
```

## 9. config.yml 수정

- `always_include`: 항상 deep scan할 종목입니다.
- `manual_risk_symbols`: 사건성 위험이나 매수 제한 종목을 지정합니다.
- `liquidity.min_trade_value_krw_for_buy_signal`: BUY_NOW 최소 24H 거래대금 기준입니다.
- `alerts.notify_grades`: 개별 알림을 보낼 등급입니다.
- `alerts.summary_grades`: 요약에 포함할 등급입니다.
- `scan.deep_scan_trade_value_top_n`: 거래대금 상위 deep scan 후보 수입니다.
- `scan.deep_scan_candidate_limit`: 최종 deep scan 후보 상한입니다.
- `scan.rotate_batch_size`: 매 실행마다 추가로 돌려볼 나머지 종목 수입니다.
- `scan.request_sleep_seconds`: Public API 요청 사이 대기 시간입니다.
- `scan.http_timeout_seconds`: HTTP 요청 타임아웃입니다.
- `scan.max_runtime_seconds`: 한 번의 스캔 최대 실행 시간입니다.

`manual_risk_symbols`에서 `allow_buy_signal: false`인 종목은 분석은 해도 `BUY_NOW`로 올리지 않습니다.

## 10. 알림 예시

```text
BUY_NOW_B | PUFFER/KRW
현재가: 30.4원
24H: 저점 29.7원 / 고점 36.8원
Range position: 0.12
모델: Sweep Reversal Buy

근거:
- 24H 저점 방어
- 15m 몸통 이탈 없음
- 목표 DOL까지 RR 1.8

전략:
- 공격형 진입: 29.7~30.5원
- BID: 28.4~29.5원
- 1차 목표: 33원
- 2차 목표: 36.8원
- 무효화: 29.7원 아래 15분봉 몸통 마감

비고:
소액만. 최종 판단은 사용자 몫.
```

## 11. 문제 해결

- 텔레그램이 오지 않으면 GitHub Secrets 이름과 chat_id를 확인하세요.
- `dry-run`에서는 텔레그램을 보내지 않고 콘솔에 출력합니다.
- `--skip-telegram`은 텔레그램 전송과 dry-run 메시지 출력을 모두 건너뛰고 짧은 실행 요약만 출력합니다.
- 빗썸 응답 필드가 비어 있거나 캔들이 부족하면 해당 종목은 건너뜁니다.
- 너무 긴 텔레그램 메시지는 자동으로 여러 번 나누어 전송합니다.
- 중복 알림은 `state/sent_signals.json`에 최근 signal_id를 저장해 줄입니다.

## 12. 민감정보 경고

public repository에 `.env`, 텔레그램 토큰, chat_id, 개인 포트폴리오 파일을 올리지 마세요. 이 프로젝트는 무료 운영을 목표로 하며 빗썸 Public API와 GitHub Actions만 사용합니다.
