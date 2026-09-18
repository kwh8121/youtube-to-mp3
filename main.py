#!/usr/bin/env -S .venv/bin/python3
"""유튜브 링크에서 오디오를 추출해 mp3 파일로 저장하는 CLI 도구."""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yt_dlp

MAX_TITLE_WORDS = 7


def truncate_title(title: str, max_words: int = MAX_TITLE_WORDS) -> str:
    """제목을 공백 기준 최대 max_words 단어로 줄인다."""
    words = title.split()
    if len(words) <= max_words:
        return title
    return " ".join(words[:max_words])


def unique_path(path: Path) -> Path:
    """같은 이름의 파일이 이미 있으면 (2), (3)... 을 붙여 겹치지 않는 경로를 만든다."""
    if not path.exists():
        return path
    i = 2
    while True:
        candidate = path.with_name(f"{path.stem} ({i}){path.suffix}")
        if not candidate.exists():
            return candidate
        i += 1


def download_audio(
    url: str, output_dir: str, quality: str, no_playlist: bool = False
) -> list[str]:
    """유튜브 링크(단일 영상 또는 재생목록)에서 오디오를 추출해 mp3로 저장한다.

    반환값은 실제로 생성된 mp3 파일 경로 목록이다.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    downloaded_files: list[str] = []

    def on_postprocessor_finished(d: dict) -> None:
        if d["status"] == "finished" and d["postprocessor"] == "ExtractAudio":
            # 훅 호출 시점의 filepath는 아직 변환 전 확장자를 가리키고 있어
            # mp3로 확장자를 보정해야 최종 경로가 된다.
            # 이 훅은 같은 파일에 대해 두 번 호출될 수 있어 중복을 제거한다.
            mp3_path = str(Path(d["info_dict"]["filepath"]).with_suffix(".mp3"))
            if mp3_path not in downloaded_files:
                downloaded_files.append(mp3_path)

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": str(Path(output_dir) / "%(title)s.%(ext)s"),
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": quality,
            },
            # 영상 챕터(없으면 yt-dlp가 설명란 타임스탬프에서 추출한 챕터)를 mp3에
            # 삽입해 둔다. 그래야 나중에 로컬 파일만으로도 챕터 기준 분할이 가능하다.
            {
                "key": "FFmpegMetadata",
                "add_metadata": False,
                "add_chapters": True,
                "add_infojson": False,
            },
        ],
        "postprocessor_hooks": [on_postprocessor_finished],
        "noplaylist": no_playlist,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    # 영상 제목이 그대로 파일명이 되면 너무 길어질 수 있어 다운로드가 끝난 뒤
    # 최대 MAX_TITLE_WORDS 단어로 줄여서 다시 이름을 붙인다. 이후 무음 분할
    # 단계도 이 파일명(stem)을 기준으로 폴더/트랙 이름을 짓기 때문에 자동으로
    # 같은 규칙이 적용된다.
    renamed_files = []
    for path_str in downloaded_files:
        path = Path(path_str)
        short_stem = truncate_title(path.stem)
        if short_stem == path.stem:
            renamed_files.append(path_str)
            continue
        new_path = unique_path(path.with_name(short_stem + path.suffix))
        path.rename(new_path)
        renamed_files.append(str(new_path))

    return renamed_files


def get_duration(path: str) -> float:
    """ffprobe로 오디오 파일의 총 길이(초)를 구한다."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            path,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def detect_silences(
    path: str, noise_db: str, silence_dur: float
) -> tuple[list[tuple[float, float]], float | None]:
    """ffmpeg silencedetect로 무음 구간(시작, 끝) 목록과 파일 총 길이(초)를 구한다.

    총 길이는 ffmpeg가 로그에 함께 출력하는 Duration 값을 재사용해 ffprobe를 따로
    실행하지 않는다. 로그에서 길이를 얻지 못하면 None을 돌려준다.
    """
    result = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-i",
            path,
            "-af",
            f"silencedetect=noise={noise_db}:d={silence_dur}",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        # ffmpeg가 실패했는데도 "무음 없음"으로 오인하지 않도록 종료 코드를 확인한다.
        check=True,
    )
    starts = [float(m) for m in re.findall(r"silence_start:\s*([0-9.]+)", result.stderr)]
    ends = [float(m) for m in re.findall(r"silence_end:\s*([0-9.]+)", result.stderr)]
    n = min(len(starts), len(ends))
    silences = list(zip(starts[:n], ends[:n]))

    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
    if not match:
        return silences, None
    hours, minutes, seconds = match.groups()
    return silences, int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def compute_split_points(
    silences: list[tuple[float, float]], duration: float, min_track: float
) -> list[float]:
    """무음 구간 목록에서 실제 트랙 경계로 쓸 분할 지점을 계산한다.

    파일 끝 3초 이내의 무음은 마지막 곡의 페이드아웃일 뿐이므로 제외한다.
    남은 후보는 뒤에서부터 훑어 min_track보다 가까운 후보들을 하나로 묶고
    그중 가장 뒤(늦은 시각)의 후보만 채택한다. 이렇게 뒤쪽 기준으로 묶어야,
    곡이 끝난 것처럼 무음이 있다가 짧게 다시 이어지는 구간(히든 트랙 등)이
    뒤 곡이 아니라 앞 곡에 붙게 된다.
    """
    candidates = [
        (start + end) / 2 for start, end in silences if duration - start >= 3
    ]

    merged = []
    for point in reversed(candidates):
        if merged and merged[-1] - point < min_track:
            continue
        merged.append(point)
    merged.reverse()

    splits = []
    last_point = 0.0
    for point in merged:
        if point - last_point < min_track:
            continue
        splits.append(point)
        last_point = point

    if splits and duration - splits[-1] < min_track:
        splits.pop()

    return splits


def split_audio_by_silence(
    path: str, noise_db: str, silence_dur: float, min_track: float
) -> None:
    """무음 구간을 기준으로 오디오 파일을 여러 트랙으로 분할한다."""
    silences, duration = detect_silences(path, noise_db, silence_dur)
    if duration is None:
        duration = get_duration(path)
    splits = compute_split_points(silences, duration, min_track)

    if not splits:
        print(f"알림: '{Path(path).name}'에서 분할 경계를 찾지 못해 건너뜁니다.")
        return

    title = Path(path).stem
    boundaries = [0.0, *splits, duration]
    segments = [
        (boundaries[i], boundaries[i + 1], f"{title} - {i + 1:02d}")
        for i in range(len(boundaries) - 1)
    ]
    out_dir = write_tracks(path, segments)

    print(f"분할 완료: '{title}' -> {len(segments)}개 트랙 ({out_dir})")


def write_tracks(path: str, segments: list[tuple[float, float, str]]) -> Path:
    """(시작, 끝, 파일명 stem) 목록대로 오디오를 잘라 원본 이름의 폴더에 저장한다.

    트랙마다 ffmpeg를 따로 실행하면 매번 파일 처음부터 다시 읽어야 해서 트랙 수가
    많을수록 느려진다. 대신 segment 먹서로 원본을 한 번만 읽으며 모든 경계에서
    재인코딩 없이 자른다. 구간은 서로 이어져 있다고 가정하며, 구간 사이에 빈틈이
    있으면 그 부분은 앞 트랙에 포함된다.

    반환값은 트랙이 저장된 디렉토리다.
    """
    src = Path(path)
    out_dir = src.parent / src.stem
    out_dir.mkdir(exist_ok=True)

    first_start = segments[0][0]
    total = segments[-1][1] - first_start
    # 입력 탐색(-ss) 후에는 타임스탬프가 0부터 시작하므로 경계도 첫 구간 기준으로 옮긴다.
    split_times = ",".join(f"{start - first_start:.3f}" for start, _, _ in segments[1:])

    # 먹서는 번호 패턴 파일명만 만들 수 있어 임시 디렉토리에 자른 뒤 최종 이름으로 옮긴다.
    with tempfile.TemporaryDirectory(dir=out_dir) as tmp_dir:
        cmd = [
            "ffmpeg",
            "-y",
            "-nostdin",
            "-loglevel",
            "error",
            "-ss",
            str(first_start),
            "-i",
            path,
            "-t",
            str(total),
            # 원본에 삽입된 챕터 전체가 각 트랙에 그대로 복사되지 않도록 제거한다.
            "-map_chapters",
            "-1",
            "-c",
            "copy",
            "-f",
            "segment",
            # 각 트랙의 재생 시간이 0부터 시작하도록 타임스탬프를 초기화한다.
            "-reset_timestamps",
            "1",
        ]
        if split_times:
            cmd += ["-segment_times", split_times]
        cmd.append(str(Path(tmp_dir) / "%03d.mp3"))
        subprocess.run(cmd, check=True)

        parts = sorted(Path(tmp_dir).glob("*.mp3"))
        if len(parts) != len(segments):
            raise RuntimeError(
                f"예상한 트랙 수({len(segments)})와 실제로 잘린 수({len(parts)})가 다릅니다."
            )
        for part, (_, _, stem) in zip(parts, segments):
            part.replace(out_dir / f"{stem}.mp3")

    return out_dir


def get_chapters(path: str) -> list[tuple[float, float, str]]:
    """ffprobe로 오디오 파일에 삽입된 챕터(시작, 끝, 제목) 목록을 구한다."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_chapters", "-of", "json", path],
        capture_output=True,
        text=True,
        check=True,
    )
    chapters = json.loads(result.stdout).get("chapters", [])
    return [
        (
            float(c["start_time"]),
            float(c["end_time"]),
            c.get("tags", {}).get("title", ""),
        )
        for c in chapters
    ]


def sanitize_filename(name: str, max_bytes: int = 200) -> str:
    """파일명에 쓸 수 없는 문자를 '_'로 바꾸고, 파일시스템 한도를 넘지 않게 자른다."""
    name = re.sub(r'[\\/:*?"<>|]', "_", name).strip(" .")
    # 한글 등 멀티바이트 문자를 고려해 바이트 기준으로 자른다.
    return name.encode()[:max_bytes].decode(errors="ignore").strip(" .")


def split_audio_by_chapters(path: str) -> None:
    """파일에 삽입된 챕터를 기준으로 오디오 파일을 여러 트랙으로 분할한다."""
    chapters = get_chapters(path)

    if len(chapters) < 2:
        print(
            f"알림: '{Path(path).name}'에 챕터 정보가 없어 건너뜁니다. "
            "영상에 챕터나 설명란 타임스탬프가 없다면 --split-by-silence를 시도하세요. "
            "챕터 삽입 기능이 생기기 전에 받은 로컬 파일이라면 유튜브 링크로 다시 받아야 합니다."
        )
        return

    title = Path(path).stem
    segments = []
    for i, (start, end, chapter_title) in enumerate(chapters, start=1):
        # 설명란 타임스탬프의 "1." "01)" 같은 업로더 번호는 트랙 번호와 겹치므로 떼어낸다.
        chapter_title = re.sub(r"^\s*\d+\s*[.)]\s*", "", chapter_title)
        # 번호를 앞에 붙여 곡 순서를 유지하고, 챕터 제목이 겹쳐도 파일명이 충돌하지 않게 한다.
        name = sanitize_filename(chapter_title)
        stem = f"{i:02d} - {name}" if name else f"{title} - {i:02d}"
        segments.append((start, end, stem))
    out_dir = write_tracks(path, segments)

    print(f"분할 완료: '{title}' -> {len(segments)}개 트랙 ({out_dir})")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="유튜브 링크에서 오디오를 추출해 mp3로 변환합니다."
    )
    parser.add_argument(
        "url", help="유튜브 영상/재생목록 링크 또는 이미 받아둔 로컬 mp3 파일 경로"
    )
    parser.add_argument(
        "--output-dir",
        default="downloads",
        help="mp3 파일을 저장할 디렉토리 (기본값: downloads)",
    )
    parser.add_argument(
        "--quality",
        default="192",
        help="mp3 비트레이트(kbps) (기본값: 192)",
    )
    parser.add_argument(
        "--no-playlist",
        action="store_true",
        help="재생목록 링크라도 URL에 지정된 영상 하나만 다운로드한다",
    )
    split_group = parser.add_mutually_exclusive_group()
    split_group.add_argument(
        "--split-by-silence",
        action="store_true",
        help="다운로드한 mp3를 무음 구간 기준으로 여러 트랙으로 분할한다 (재생목록 모음 영상용)",
    )
    split_group.add_argument(
        "--split-by-chapters",
        action="store_true",
        help="영상 챕터(또는 설명란 타임스탬프) 기준으로 mp3를 곡별로 분할한다 (곡 사이 무음이 없는 모음 영상용)",
    )
    parser.add_argument(
        "--noise-db",
        default="-35dB",
        help="무음으로 간주할 볼륨 임계값 (기본값: -35dB)",
    )
    parser.add_argument(
        "--silence-dur",
        type=float,
        default=1.5,
        help="무음으로 인정할 최소 지속시간, 초 (기본값: 1.5)",
    )
    parser.add_argument(
        "--min-track",
        type=float,
        default=30.0,
        help="분할된 트랙의 최소 길이, 초 (기본값: 30)",
    )
    return parser.parse_args()


def split_file(path: str, args: argparse.Namespace) -> None:
    """명령행 인자에 지정된 방식으로 파일 하나를 분할한다."""
    if args.split_by_chapters:
        split_audio_by_chapters(path)
    else:
        split_audio_by_silence(path, args.noise_db, args.silence_dur, args.min_track)


def main() -> None:
    args = parse_args()

    if Path(args.url).is_file():
        # 로컬 mp3 파일이 주어지면 다운로드 없이 바로 분할 대상으로 사용한다.
        files = [args.url]
    else:
        try:
            files = download_audio(args.url, args.output_dir, args.quality, args.no_playlist)
        except yt_dlp.utils.DownloadError as e:
            print(f"오류: 다운로드에 실패했습니다 - {e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:  # ffmpeg 미설치 등 후처리 오류 대비
            print(f"오류: {e}", file=sys.stderr)
            sys.exit(1)

    if not files or not (args.split_by_chapters or args.split_by_silence):
        return

    # 무음 탐지는 파일 전체를 디코딩해 CPU를 많이 쓰지만 ffmpeg 프로세스 하나는 사실상
    # 코어 하나만 쓴다. 실제 작업은 하위 프로세스가 하므로 GIL 영향이 없어, 재생목록처럼
    # 파일이 여러 개면 스레드로 동시에 분할한다.
    workers = min(len(files), os.cpu_count() or 1)
    failed = False
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(split_file, f, args): f for f in files}
        for future in as_completed(futures):
            # 한 파일의 분할 실패가 나머지 파일 처리를 막지 않도록 파일 단위로 오류를 잡는다.
            try:
                future.result()
            except (subprocess.CalledProcessError, OSError, RuntimeError, ValueError) as e:
                print(
                    f"오류: '{Path(futures[future]).name}' 분할에 실패했습니다 - {e}",
                    file=sys.stderr,
                )
                failed = True

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
