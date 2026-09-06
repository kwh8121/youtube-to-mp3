#!/usr/bin/env -S .venv/bin/python3
"""유튜브 링크에서 오디오를 추출해 mp3 파일로 저장하는 CLI 도구."""

import argparse
import re
import subprocess
import sys
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


def download_audio(url: str, output_dir: str, quality: str, no_playlist: bool = False) -> list:
    """유튜브 링크(단일 영상 또는 재생목록)에서 오디오를 추출해 mp3로 저장한다.

    반환값은 실제로 생성된 mp3 파일 경로 목록이다.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    downloaded_files = []

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
            }
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


def detect_silences(path: str, noise_db: str, silence_dur: float) -> list:
    """ffmpeg silencedetect로 무음 구간(시작, 끝) 목록을 구한다."""
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
    )
    starts = [float(m) for m in re.findall(r"silence_start:\s*([0-9.]+)", result.stderr)]
    ends = [float(m) for m in re.findall(r"silence_end:\s*([0-9.]+)", result.stderr)]
    n = min(len(starts), len(ends))
    return list(zip(starts[:n], ends[:n]))


def compute_split_points(silences: list, duration: float, min_track: float) -> list:
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
    duration = get_duration(path)
    silences = detect_silences(path, noise_db, silence_dur)
    splits = compute_split_points(silences, duration, min_track)

    if not splits:
        print(f"알림: '{Path(path).name}'에서 분할 경계를 찾지 못해 건너뜁니다.")
        return

    title = Path(path).stem
    out_dir = Path(path).parent / title
    out_dir.mkdir(exist_ok=True)

    boundaries = [0.0, *splits, duration]
    for i in range(len(boundaries) - 1):
        out_path = out_dir / f"{title} - {i + 1:02d}.mp3"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-nostdin",
                "-loglevel",
                "error",
                "-i",
                path,
                "-ss",
                str(boundaries[i]),
                "-to",
                str(boundaries[i + 1]),
                "-c",
                "copy",
                str(out_path),
            ],
            check=True,
        )

    print(f"분할 완료: '{title}' -> {len(boundaries) - 1}개 트랙 ({out_dir})")


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
    parser.add_argument(
        "--split-by-silence",
        action="store_true",
        help="다운로드한 mp3를 무음 구간 기준으로 여러 트랙으로 분할한다 (재생목록 모음 영상용)",
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

    if args.split_by_silence:
        for f in files:
            split_audio_by_silence(f, args.noise_db, args.silence_dur, args.min_track)


if __name__ == "__main__":
    main()
