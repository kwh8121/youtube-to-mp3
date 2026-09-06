# music

유튜브 링크에서 오디오를 추출해 mp3 파일로 저장하는 CLI 도구.

## 설치

```bash
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
- 파일 제목이 7단어를 넘으면 앞 7단어만 남겨서 파일명을 짧게 줄입니다.
- 같은 이름의 파일이 이미 있으면 `(2)`, `(3)`... 을 붙여 겹치지 않게 저장합니다.

## 옵션

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `url` | (필수) | 유튜브 영상/재생목록 링크 또는 이미 받아둔 로컬 mp3 파일 경로 |
| `--output-dir` | `downloads` | mp3 파일을 저장할 디렉토리 |
| `--quality` | `192` | mp3 비트레이트(kbps) |
| `--no-playlist` | - | 재생목록 링크라도 URL에 지정된 영상 하나만 다운로드 |
| `--split-by-silence` | - | 다운로드(또는 로컬) mp3를 무음 구간 기준으로 여러 트랙으로 분할 (재생목록 모음 영상용) |
| `--noise-db` | `-35dB` | 무음으로 간주할 볼륨 임계값 |
| `--silence-dur` | `1.5` | 무음으로 인정할 최소 지속시간(초) |
| `--min-track` | `30.0` | 분할된 트랙의 최소 길이(초) |

## 사용 예시

### 단일 영상 다운로드

```bash
./main.py "https://www.youtube.com/watch?v=VIDEO_ID"
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
