# music

유튜브 링크에서 오디오를 추출해 mp3 파일로 저장하는 CLI 도구.

저장소: <https://github.com/kwh8121/youtube-to-mp3>

## 설치

```bash
git clone https://github.com/kwh8121/youtube-to-mp3.git
cd youtube-to-mp3

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

`ffmpeg`, `ffprobe`가 시스템에 설치되어 있어야 합니다.

## 기본 사용법

```bash
./main.py <유튜브 링크>
```

- 단일 영상 또는 재생목록 링크를 지원합니다.
- 이미 다운로드해둔 로컬 mp3 파일 경로를 넣으면 다운로드 없이 바로 분할 등의 후처리만 수행합니다.
- 결과 mp3 파일은 기본적으로 `downloads/` 디렉토리에 저장됩니다.
- 파일 제목이 7단어를 넘으면 앞 7단어만 남겨서 파일명을 짧게 줄입니다. 제목 끝의 점과 하이픈은 떼어내 `제목..mp3`, `제목 -.mp3`처럼 되지 않게 합니다.
- yt-dlp가 파일명에 넣는 전각 대체 문자는 일반 문자로 바꿉니다. `｜ ： ⧸ ⧹`는 `-`로, `＂`는 `'`로 바꾸고 `？ ＊ ＜ ＞`는 지웁니다. (예: `Hush - Freaky ｜ Trap ｜ NCS` → `Hush - Freaky - Trap - NCS`)
- 같은 이름의 파일이 이미 있으면 `(2)`, `(3)`... 을 붙여 겹치지 않게 저장합니다.
- 영상에 챕터(또는 설명란 타임스탬프)가 있으면 mp3에 챕터 정보를 함께 저장합니다. 나중에 로컬 파일만으로 `--split-by-chapters` 분할을 할 수 있습니다.

## 옵션

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `url` | (필수) | 유튜브 영상/재생목록 링크 또는 이미 받아둔 로컬 mp3 파일 경로 |
| `--output-dir` | `downloads` | mp3 파일을 저장할 디렉토리 |
| `--quality` | `192` | mp3 비트레이트(kbps) |
| `--no-playlist` | - | 재생목록 링크라도 URL에 지정된 영상 하나만 다운로드 |
| `--split-by-chapters` | - | 영상 챕터(또는 설명란 타임스탬프) 기준으로 곡별 분할. `--split-by-silence`와 함께 쓸 수 없음 |
| `--split-by-silence` | - | 다운로드(또는 로컬) mp3를 무음 구간 기준으로 여러 트랙으로 분할 (재생목록 모음 영상용) |
| `--noise-db` | `-35dB` | 무음으로 간주할 볼륨 임계값. `-30dB`처럼 대문자 `dB` 단위를 붙여 입력 |
| `--silence-dur` | `1.5` | 무음으로 인정할 최소 지속시간(초) |
| `--min-track` | `30.0` | 분할된 트랙의 최소 길이(초) |

## 사용 예시

### 단일 영상 다운로드

```bash
./main.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

### 재생목록 전체 다운로드

재생목록 링크를 넘기면 포함된 영상을 모두 mp3로 받습니다.

```bash
./main.py "https://www.youtube.com/playlist?list=PLxxxx"
```

### 저장 디렉토리와 음질 지정

```bash
./main.py "https://www.youtube.com/watch?v=VIDEO_ID" --output-dir my_music --quality 320
```

### 재생목록/라디오 링크에서 영상 하나만 받기

`list=...&start_radio=1`이 붙은 "라디오 믹스" 링크는 관련 영상이 계속 이어지는
재생목록으로 인식돼 수백 개가 한꺼번에 받아질 수 있습니다. `--no-playlist`를
추가하면 URL에 지정된 영상 하나만 받습니다.

```bash
./main.py "https://www.youtube.com/watch?v=VIDEO_ID&list=RDxxxx&start_radio=1" --no-playlist
```

### 여러 곡이 이어진 모음 영상을 챕터 기준으로 분할

모음 영상은 대부분 챕터나 설명란 타임스탬프(`00:00 곡명`, `04:50 곡명` ...)가 있습니다.
이 정보로 곡 경계를 정확히 잡기 때문에, 곡이 끊김 없이 이어지는(크로스페이드) 영상도
나눌 수 있습니다. 가능하면 무음 분할보다 이 방법을 먼저 쓰는 것을 권장합니다.

```bash
./main.py "https://www.youtube.com/watch?v=VIDEO_ID" --split-by-chapters
```

분할 결과는 `downloads/<제목>/` 폴더 아래 `01 - <챕터 제목>.mp3`, `02 - <챕터 제목>.mp3` ...
형식으로 저장됩니다. 챕터 제목 앞에 붙은 `1.`, `01)` 같은 업로더 번호는 떼어냅니다.
챕터 제목에서 파일명에 쓸 수 없는 문자는 다운로드 파일명과 같은 규칙으로 바꿉니다.
(`| : / \`는 `-`로, `"`는 `'`로 바꾸고 `? * < >`는 지움. 예: `두번째: 곡?` → `두번째 - 곡`)

한 번 받아둔 파일에도 챕터가 저장되어 있으므로 로컬 파일로 다시 분할할 수 있습니다.

```bash
./main.py "downloads/모음 영상 제목.mp3" --split-by-chapters
```

챕터 저장 기능이 추가되기 전에 받은 파일에는 챕터가 없습니다. 이런 파일은 유튜브 링크로
다시 받아야 합니다. 영상 자체에 챕터와 타임스탬프가 모두 없다면 아래의 무음 기준 분할을 사용합니다.

### 여러 곡이 이어진 모음 영상을 무음 기준으로 분할

한 영상에 여러 곡이 이어 붙어 있는 "모음"/플레이리스트 영상을 다운로드한 뒤,
곡 사이 무음 구간을 찾아 개별 트랙 파일로 나눕니다.

```bash
./main.py "https://www.youtube.com/watch?v=VIDEO_ID" --split-by-silence
```

분할 결과는 `downloads/<제목>/` 폴더 아래 `<제목> - 01.mp3`, `<제목> - 02.mp3` ... 형식으로 저장됩니다.

무음 감지가 잘 안 되면 임계값을 조정합니다.

```bash
./main.py "https://www.youtube.com/watch?v=VIDEO_ID" --split-by-silence --noise-db -30dB --silence-dur 1.0 --min-track 20
```

### 이미 받아둔 로컬 mp3 파일 분할

다운로드는 이미 끝났고 분할만 다시 하고 싶다면, URL 대신 로컬 파일 경로를 넘깁니다.

```bash
./main.py "downloads/모음 영상 제목.mp3" --split-by-silence
```

### 재생목록을 받으면서 각 영상을 곡 단위로 분할

`--split-by-silence`, `--split-by-chapters`는 다운로드된 파일 각각에 적용되므로,
재생목록과 함께 쓰면 영상별로 분할이 수행됩니다. 여러 파일은 CPU 코어 수만큼 동시에
분할하므로, 파일별 완료 메시지는 재생목록 순서와 다르게 출력될 수 있습니다.

```bash
./main.py "https://www.youtube.com/playlist?list=PLxxxx" --split-by-silence --output-dir my_music
```

어떤 파일의 분할에 실패하면(손상된 파일 등) 오류 메시지를 출력하고 나머지 파일은 계속
처리합니다. 실패한 파일이 하나라도 있으면 종료 코드 `1`로 끝나므로 스크립트에서 확인할 수 있습니다.

## 분할 동작 참고

- 재인코딩 없이 원본 mp3를 한 번만 읽으며 모든 경계에서 잘라내므로, 트랙이 많은 긴 모음
  영상도 빠르게 분할됩니다(60분 파일을 20곡으로 나누는 데 약 1초).
- 재인코딩을 하지 않기 때문에 경계는 mp3 프레임 단위(약 26ms)로 맞춰집니다. 귀로 구분되는 차이는 없습니다.
- 같은 파일을 다시 분할하면 `<제목>/` 폴더의 같은 이름 트랙 파일을 덮어씁니다.
- 챕터 기준 분할에서 챕터 사이에 빈 구간이 있으면 그 구간은 앞 트랙에 포함됩니다.

### 전체 옵션 확인

```bash
./main.py --help
```
