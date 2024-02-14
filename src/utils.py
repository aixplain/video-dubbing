import json
import os
import shutil
import tempfile
import traceback
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import boto3
import pysrt
import requests
from dotenv import find_dotenv, load_dotenv
from nltk.tokenize import sent_tokenize

from src.logger import root_logger
from src.paths import paths


load_dotenv(find_dotenv(paths.PROJECT_ROOT_DIR / "vars.env"), override=True)
load_dotenv(find_dotenv(paths.PROJECT_ROOT_DIR / "secrets.env"), override=True)  # THIS SHOULD ALWAYS BE BEFORE aixplain import

from aixplain.factories.model_factory import ModelFactory
from aixplain.factories.pipeline_factory import PipelineFactory

try:
    from aixplain.utils.file_utils import *
except:
    from aixplain.utils.file_utils import *


subtitle_pipeline = None #PipelineFactory.get(os.getenv("SUBTITLE_PIPELINE_ID"))
if os.getenv("SUBTITLE_PIPELINE_ID"):
    subtitle_pipeline = PipelineFactory.get(os.getenv("SUBTITLE_PIPELINE_ID"))
else:
    with open(paths.PIPELINE_INFO_PATH) as f:
        pipeline_info = json.load(f)
    subtitle_pipeline = PipelineFactory._PipelineFactory__from_response(pipeline_info)

chatgpt_model = ModelFactory.get("6414bd3cd09663e9225130e8")

BACKEND_URL = "https://platform-api.aixplain.com/assets/pipeline/execution/check/"
app_logger = root_logger.getChild(Path(__file__).stem)


# s3 = boto3.client("s3", aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"), aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"))
# S3_BUCKET = os.getenv("S3_BUCKET")
# S3_FOLDER = os.getenv("S3_FOLDER")


import copy
import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List

import pysrt
import requests
from aixplain.factories import ModelFactory
from moviepy.editor import AudioFileClip, CompositeAudioClip, VideoFileClip
from pydub import AudioSegment

from src.logger import root_logger
from src.models import MODELS
from src.paths import paths


def download_mp3(url, save_path):
    response = requests.get(url)
    if response.status_code == 200:
        with open(save_path, "wb") as mp3_file:
            mp3_file.write(response.content)
        print("MP3 file downloaded successfully.")
        return True
    else:
        print(f"Failed to download MP3 file. Status code: {response.status_code}")
        return False


app_logger = root_logger.getChild(Path(__file__).stem)


SPEAKING_RATES = {"slow": 65, "average": 150, "high": 220}

FRAME_RATE = 24000  # 24 KHz


def form_url_from_job_id(job_id: str):
    return BACKEND_URL + job_id


def get_audio(model_id, text, output_file):
    model = ModelFactory.get(model_id)
    response = model.run(text)
    if response["status"] == "SUCCESS":
        if download_mp3(response["data"], output_file):
            return output_file
    raise Exception("Failed to get audio")


def replace_audio_beginning_end(input_path, output_path, intro_path: str = paths.DATA_DIR / "intro.mp3", ending_path: str = paths.DATA_DIR / "ending.mp3"):  # type: ignore
    # Load audio files
    intro_audio = AudioSegment.from_file(intro_path)
    intro_audio = intro_audio - 5

    ending_audio = AudioSegment.from_file(ending_path)
    ending_audio = ending_audio - 10
    input_audio = AudioSegment.from_file(input_path)

    # Calculate the duration of the input audio
    input_duration = len(input_audio)
    intro_duration = len(intro_audio)
    ending_duration = len(ending_audio)

    assert input_duration > intro_duration + ending_duration, "Input audio must be longer than the intro and ending combined"

    # Replace the beginning and ending of the input audio
    output_audio = intro_audio + input_audio[intro_duration:-ending_duration] + ending_audio

    # Export the output audio to a file
    output_audio.export(output_path, format="mp3")


def load_subtitles(fname: str):
    subs = pysrt.open(fname)

    segments = []
    for sub in subs:
        segment = {
            "index": sub.index,
            "position": sub.position,
            "text": sub.text.replace("\n", " ").strip(),
            "start": datetime(2020, 1, 1, sub.start.hours, sub.start.minutes, sub.start.seconds, sub.start.milliseconds * 1000),
            "end": datetime(2020, 1, 1, sub.end.hours, sub.end.minutes, sub.end.seconds, sub.end.milliseconds * 1000),
        }
        segments.append(segment)
    return segments


def connect_sequences_sentence_based(segments: List):
    new_segments = []  # type: ignore
    idx = 1
    for i, s in enumerate(segments):
        if i > 0:
            start, start_id = s["start"], s["id"]
            prev_end, prev_id = segments[i - 1]["end"], segments[i - 1]["id"]

            if start_id == prev_id and start == prev_end:
                text = new_segments[-1]["text"] + " " + s["text"]
                new_segments[-1]["text"] = text
                new_segments[-1]["end"] = s["end"]
            else:
                new_segments.append(s)
                s["index"] = idx
                idx += 1
        else:
            new_segments.append(s)
            s["index"] = idx
            idx += 1
    return new_segments


def get_words_pminute(segments: List):
    for i, segment in enumerate(segments):
        start = segment["start"]
        end = segment["end"]
        text = segment["text"]
        seconds = (end - start).total_seconds()
        words_pminute = int(len(text.split()) / (seconds / 60))
        segments[i]["wpm"] = words_pminute
    return segments


def adjust_speed(audio_file: str, model_id: str, speed: int, text: str, output_audio: str = None):
    model = ModelFactory.get(model_id)

    text = f"<speak><prosody rate='{speed}%'>{text}</prosody></speak>"
    response = model.run(text)
    if output_audio is None:
        output_audio = audio_file

    if response["status"] == "SUCCESS":
        if download_mp3(response["data"], output_audio):
            return output_audio
    raise Exception("Failed to adjust speed")


def update_segment(segment_path: str, new_segment: Dict):
    with open(segment_path) as f:
        segments = json.load(f)
    updated = False
    for i, s in enumerate(segments):
        if s["index"] == new_segment["index"]:
            # reaplace audio with new audio
            shutil.copy(new_segment["audio"], s["audio"])
            new_segment["audio"] = s["audio"]
            segments[i] = new_segment
            updated = True
            break
    if not updated:
        segments.append(new_segment)

    with open(segment_path, "w") as f:
        json.dump(segments, f)
    return segments


def stretch_squeeze(segments: List):
    for i, s in enumerate(segments):
        start = s["start"]
        end = s["end"]
        text = s["text"]
        words_pminute = s["wpm"]

        try:
            prev_start = segments[i - 1]["start"]
        except:
            prev_start = start

        try:
            post_end = segments[i + 1]["end"]
        except:
            post_end = end

        pwords_pminute = copy.copy(words_pminute)
        if pwords_pminute < SPEAKING_RATES["slow"]:
            while end > start and words_pminute < SPEAKING_RATES["slow"]:
                start += timedelta(seconds=0.01)
                end -= timedelta(seconds=0.01)

                seconds = (end - start).total_seconds()
                words_pminute = int(len(text.split()) / (seconds / 60))

            if SPEAKING_RATES["slow"] <= words_pminute <= SPEAKING_RATES["high"] and start < end:
                segments[i]["start"] = start
                segments[i]["end"] = end
                segments[i]["wpm"] = words_pminute
        elif pwords_pminute > SPEAKING_RATES["high"]:
            while start >= prev_start and end <= post_end and words_pminute > SPEAKING_RATES["high"]:
                start -= timedelta(seconds=0.01)
                end += timedelta(seconds=0.01)

                seconds = (end - start).total_seconds()
                words_pminute = int(len(text.split()) / (seconds / 60))

            if SPEAKING_RATES["slow"] <= words_pminute <= SPEAKING_RATES["high"] and start >= prev_start and end <= post_end:
                segments[i]["start"] = start
                segments[i]["end"] = end
                segments[i]["wpm"] = words_pminute
    return segments


def remove_cutoff_date(time: datetime):
    cut_off_date = datetime(2020, 1, 1)
    time -= cut_off_date  # type: ignore
    return time


def create_audio_segments(segments: List[Dict], model_id: str, language_folder: str, voice_name: str):
    model = ModelFactory.get(model_id)
    audio_folder = os.path.join(language_folder, "segments", voice_name)
    if not os.path.exists(audio_folder):
        os.makedirs(audio_folder, exist_ok=True)

    segment_data = []  # type: ignore
    segments_json_path = os.path.join(language_folder, f"segments-{voice_name}.json")
    if os.path.exists(segments_json_path):
        segment_data = json.load(open(segments_json_path))

    os.makedirs(audio_folder, exist_ok=True)

    # while all segmentss are not processed
    while len(segment_data) < len(segments):
        for i, segment in enumerate(segments):

            index = segment["index"]

            audio_path = os.path.join(audio_folder, f"{index}.mp3")
            # check if segment_data has the segment
            if any([s["index"] == index for s in segment_data]):
                continue

            wpm = segment["wpm"]
            text = segment["text"]
            start = remove_cutoff_date(segment["start"])
            end = remove_cutoff_date(segment["end"])

            prev_segment = segments[i - 1] if i > 0 else None
            after_segment = segments[i + 1] if i < len(segments) - 1 else None

            prev_end = timedelta(seconds=0)
            if prev_segment:
                prev_end = remove_cutoff_date(prev_segment["end"])

            after_start = end
            if after_segment:
                after_start = remove_cutoff_date(after_segment["start"])

            assert after_start > prev_end, "Duration cannot be negative"

            duration_max = (after_start - prev_end).total_seconds()
            segment_duration = (end - start).total_seconds()

            if not os.path.exists(audio_path):
                # Generate audio segment for the text
                response = model.run(text)

                download_mp3(response["data"], audio_path)

            seg_audio = AudioSegment.from_file(audio_path)

            audio_duration = seg_audio.duration_seconds

            if audio_duration <= segment_duration:  # If audio is shorter than it starts as start and end as duration
                app_logger.info(f"Audio is shorter than the segment duration: {audio_duration} < {segment_duration}")
                new_start = start.total_seconds()
                new_end = new_start + audio_duration
                speed = int((100 * audio_duration) / (new_end - new_start))
                app_logger.info(f"Updated start and end from {start} to {new_start} and {end} to {new_end}")

            elif audio_duration >= duration_max:  # If audio is longer than it and need to regenerate
                # audio is too long, need to cut
                speed = int((100 * audio_duration) / duration_max)
                app_logger.info(f"Audio is longer than the segment duration: {audio_duration} > {segment_duration}")
                audio_path = adjust_speed(audio_path, model_id, speed, text)

                seg_audio = AudioSegment.from_file(audio_path)
                audio_duration = seg_audio.duration_seconds

                new_start = prev_end.total_seconds()
                new_end = after_start.total_seconds()
                app_logger.info(f"Updated start and end from {start} to {new_start} and {end} to {new_end}")

            elif audio_duration <= duration_max - start.total_seconds():  # audio can fit in the second half of the segment
                app_logger.info(f"Audio can fit in the second half of the segment: {audio_duration} < {duration_max - start.total_seconds()}")
                new_start = start.total_seconds()
                new_end = new_start + audio_duration
                speed = int((100 * audio_duration) / (new_end - new_start))
                app_logger.info(f"Updated start and end from {start} to {new_start} and {end} to {new_end}")

            elif audio_duration < duration_max:  # audio can fit in the duration
                app_logger.info(f"Audio can fit in the segment duration: {audio_duration} < {duration_max}")
                mean_duration = ((end - start) / 2).total_seconds()

                new_start = start.total_seconds() + mean_duration - (audio_duration / 2)
                new_end = new_start + audio_duration
                speed = int((100 * audio_duration) / (new_end - new_start))
                app_logger.info(f"Updated start and end from {start} to {new_start} and {end} to {new_end}")

            max_allowed_duration = duration_max

            wpm = int(len(text.split()) / ((new_end - new_start) / 60))

            segment_info = segment.copy()
            segment_info.update(
                {
                    "start": new_start,
                    "end": new_end,
                    "audio": audio_path,
                    "duration": new_end - new_start,
                    "wpm": wpm,
                    "prev_end": prev_end.total_seconds(),
                    "after_start": after_start.total_seconds(),
                    "max_allowed_duration": max_allowed_duration,
                    "speed": speed,
                }
            )
            segment_data.append(segment_info)

    segments_json_path = os.path.join(language_folder, f"segments-{voice_name}.json")
    with open(segments_json_path, "w") as f:  # type: ignore
        json.dump(segment_data, f)  # type: ignore

    return segment_data


def synthesize_combine_audio(segments: List[Dict], audio_path: str):
    audio = AudioSegment.silent(duration=0, frame_rate=FRAME_RATE)
    prev_start = 0
    for i, s in enumerate(segments):
        wpm = s["wpm"]
        text = s["text"]
        start = s["start"]
        end = s["end"]
        duration = end - start

        start = start * 1000

        silent = AudioSegment.silent(duration=max(0, start - prev_start), frame_rate=FRAME_RATE)
        audio += silent

        seg_audio = AudioSegment.from_file(s["audio"])

        audio += seg_audio
        prev_start = audio.duration_seconds * 1000
    audio.export(audio_path, format="mp3")
    return audio_path


def get_allowed_speeds(segment: dict, new_text: str = None):
    if new_text is None:
        new_text = segment["text"]
    min_allowed_duration = float(len(new_text.split()) * 60.0 / SPEAKING_RATES["high"])
    min_allowed_speed = int((100 * segment["duration"]) / (segment["max_allowed_duration"]))
    max_allowed_speed = int((100 * segment["duration"]) / min_allowed_duration)

    return {"min_allowed_speed": min_allowed_speed, "max_allowed_speed": max_allowed_speed, "current_speed": segment["speed"]}


def adjust_segment(segment: dict, speed: int, model_id: str, new_text: str = None):
    model = ModelFactory.get(model_id)

    temp_path = os.path.join(tempfile.gettempdir(), f"{segment['index']}.mp3")

    if new_text is None:
        new_text = segment["text"]
    # (audio_file: Text, model_id: Text, speed: int, text: Text, output_audio: Text = None):
    audio_path = adjust_speed(segment["audio"], model_id, speed, new_text, temp_path)
    seg_audio = AudioSegment.from_file(audio_path)
    duration = seg_audio.duration_seconds

    min_allowed_duration = float(len(new_text.split()) * 60.0 / SPEAKING_RATES["high"])

    assert duration <= segment["max_allowed_duration"], "Audio is too long, Please increase the speed or reduce the text"
    assert duration >= min_allowed_duration, "Audio is too short, Please decrease the speed or increase the text"

    if duration <= segment["duration"]:
        new_start = segment["start"]
        new_end = new_start + duration
    else:
        new_start = segment["start"] + ((segment["duration"] - duration) / 2)
        new_end = new_start + duration

    temp_segment = segment.copy()
    temp_segment.update({"text": new_text, "speed": speed, "audio": audio_path, "duration": duration, "start": new_start, "end": new_end, "audio": audio_path})
    return temp_segment


def generate_video(video_path: str, audio_path: str, output_path: str):

    # Load video
    video = VideoFileClip(video_path)

    # Load new audio
    new_audio = AudioFileClip(audio_path)

    # Decrease the volume of the original audio
    video_audio = video.audio.volumex(0.01)  # Decrease original audio volume 99%

    # Merge the new audio with the decreased volume original audio
    audio = CompositeAudioClip([video_audio, new_audio])
    audio = audio.set_fps(FRAME_RATE)

    # save audio to a temp file
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_audio_path = os.path.join(temp_dir, f"temp.mp3")
        audio.write_audiofile(temp_audio_path)

        replace_audio_beginning_end(temp_audio_path, temp_audio_path)
        audio = AudioFileClip(temp_audio_path)

        # Set the audio of the video clip
        video = video.set_audio(audio)

        # Write the result to a file
        video.write_videofile(output_path)
        # call ffmpeg -i "/home/ubuntu/repos/ekam/data/input_subclip.mp4" -vcodec libx264 "temp.mp4"
        # then replace with original one
        # import subprocess

        # subprocess.run(["ffmpeg", "-i", output_path, "-vcodec", "libx264", f"{temp_dir}/temp.mp4"])
        # shutil.copy(f"{temp_dir}/temp.mp4", output_path)


def render_video(job_id, target_language, gender, accent, voice_name, overwrite=False):
    srt_path = paths.JOBS_DIR / job_id / "subtitles" / f"{target_language}.srt"
    if not srt_path.exists():
        app_logger.info(f"Subtitles not found in the specified path: {srt_path}")
        exit(1)

    voices = MODELS[gender][target_language]["voices"]

    voice = [v for v in voices if v["name"] == voice_name and v["accent"] == accent][0]
    if not voice:
        app_logger.info(f"Voice not found in the specified path: {voice_name} , {accent}")
        exit(1)
    model_id = voice["model_id"]  # type: ignore
    voice_name = voice["name"]  # type: ignore

    app_logger.info("Generating video...")

    segments = load_subtitles(srt_path)
    segments = get_words_pminute(segments)
    segments = stretch_squeeze(segments)

    input_video_path = paths.JOBS_DIR / job_id / "input.mov"
    output_folder = paths.JOBS_DIR / job_id / "outputs"
    output_folder.mkdir(exist_ok=True)

    language_folder = output_folder / gender / target_language / accent
    language_folder.mkdir(exist_ok=True, parents=True)

    output_video_path = language_folder / f"{voice_name}.mp4"
    audio_path = language_folder / f"{voice_name}.mp3"

    if not audio_path.exists() or overwrite:
        # audio_path = synthesize(segments, model_id, audio_path)
        segment_data = create_audio_segments(segments, model_id, language_folder, voice_name)
        audio_path = synthesize_combine_audio(segment_data, audio_path)

    if isinstance(audio_path, Path):
        audio_path = str(audio_path.resolve())

    if isinstance(output_video_path, Path):
        output_video_path = str(output_video_path.resolve())

    if isinstance(input_video_path, Path):
        input_video_path = str(input_video_path.resolve())

    if not os.path.exists(output_video_path) or overwrite:
        generate_video(input_video_path, audio_path, output_video_path)
        return output_video_path
    else:
        app_logger.warn(f"Video already exists in the specified path: {output_video_path}")
        return output_video_path


from moviepy.editor import VideoFileClip


def convert_to_mov(input_file, output_file):
    video_clip = VideoFileClip(input_file)
    video_clip.write_videofile(output_file, codec="libx264", audio_codec="aac", preset="ultrafast")


def process_video(video_file: str):
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            # check if wideo is a local file or dropbox link
            if video_file.startswith("https://www.dropbox.com"):  # https://www.dropbox.com/sh/6cvleas9yuark7u/AAATSwLuDlsUgHs9CoywUE1Qa/ENGLISH.mov
                app_logger.info("Downloading video from Dropbox...")
                # Send a GET request to the Dropbox link
                import subprocess

                # Specify the filename for the downloaded file
                tmpdir_path = Path(tmpdir)
                # check if mov or mp4
                if video_file.endswith(".mov"):
                    filename = tmpdir_path / "input.mov"
                elif video_file.endswith(".mp4"):
                    filename = tmpdir_path / "input.mp4"
                else:
                    raise Exception("Video file must be .mov or .mp4")
                subprocess.run(["wget", "-O", str(filename.resolve()), video_file])

                if str(filename.resolve()).endswith(".mp4"):
                    app_logger.info("Converting video to .mov...")
                    mov_filename = tmpdir_path / "input.mov"
                    convert_to_mov(str(filename.resolve()), str((mov_filename).resolve()))
                    filename = Path(mov_filename)

                app_logger.warning(f"Video saved to {filename}")
                video_file = str(filename.resolve())
            if not os.path.exists(video_file):
                raise Exception("Video file does not exist!")

            if video_file.endswith(".mp4"):
                tmpdir_path = Path(tmpdir)
                app_logger.info("Converting video to .mov...")
                mov_filename = tmpdir_path / "input.mov"
                convert_to_mov(video_file, str((mov_filename).resolve()))
                video_file = str((mov_filename).resolve())

            # Upload video to S3
            s3_path = upload_data(video_file,content_type = "video/quicktime")# s3.upload_file(video_file, S3_BUCKET, f"{S3_FOLDER}/{os.path.basename(video_file)}")
            parsed_url = urlparse(s3_path)
            bucket_name = parsed_url.netloc
            object_key = parsed_url.path.lstrip('/')
            s3_path = f"https://{bucket_name}.s3.amazonaws.com/{object_key}"

            # Run the pipeline
            # s3_path = f"https://{S3_BUCKET}.s3.amazonaws.com/{S3_FOLDER}/{os.path.basename(video_file)}"
            app_logger.info(f"Running pipeline for {s3_path}")
            app_logger.info("This may take a while...")
            start_response = subtitle_pipeline.run_async(s3_path)
            url = start_response["url"]
            job_id = url.split("check/")[1]

            app_logger.info(f"Pipeline  with job id {job_id} started successfully!")

            os.makedirs(paths.JOBS_DIR / job_id, exist_ok=True)
            # cp video to data folder
            shutil.copy(video_file, paths.JOBS_DIR / job_id / "input.mov")
            app_logger.info("Video moved to {}".format(paths.JOBS_DIR / job_id / "input.mov"))

        subtitles_dir = paths.JOBS_DIR / job_id / "subtitles"
        subtitles_dir.mkdir(parents=True, exist_ok=True)

        outputs_dir = paths.JOBS_DIR / job_id / "outputs"
        outputs_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        app_logger.error(f"traceback: {traceback.format_exc()}")
        os.removedirs(paths.JOBS_DIR / job_id)
        raise e

    return job_id


def check_job_status(job_id: str):
    url = form_url_from_job_id(job_id)
    poll_response = subtitle_pipeline.poll(url)
    status = poll_response["status"]
    completed = poll_response["completed"]
    progress = poll_response["progress"] if "progress" in poll_response else "0%"
    return {
        "status": status,
        "completed": completed,
        "progress": progress,
    }


def download_subtitles(job_id: str) -> bool:
    url = form_url_from_job_id(job_id)
    poll_response = subtitle_pipeline.poll(url)

    status = poll_response["status"]
    status_dict = check_job_status(job_id)
    if status == "SUCCESS":
        files_url = poll_response["data"][0]["segments"][0]["response"]
        # download files json form url as dict
        files = requests.get(files_url).json()
        # save response
        with open("response.json", "w") as f:
            json.dump(poll_response, f)
        for language, urls in files.items():
            for format, url in urls.items():
                if format == "srt":
                    response = requests.get(url)
                    if response.status_code == 200:
                        file_path = f"{language}.{format}"
                        file_path = str((paths.JOBS_DIR / job_id / "subtitles" / file_path).resolve())
                        if os.path.exists(file_path):
                            app_logger.info(f"File {file_path} already exists. Skipping...")
                            continue
                        with open(file_path, "wb") as file:
                            file.write(response.content)
                        app_logger.info(f"{file_path} downloaded successfully!")
                    else:
                        app_logger.warning(f"Failed to download {url}. Status code: {response.status_code}")
        app_logger.info("Downloaded subtitles to {}".format(paths.JOBS_DIR / job_id / "subtitles"))
        return True
    else:
        app_logger.info(f"Subtitles not ready yet. Status: {status}")

        app_logger.info("Completed: {}".format(status_dict["completed"]))
        app_logger.info("Progress: {}".format(status_dict["progress"]))
        raise Exception("Subtitles not ready yet. Status: {}".format(status_dict["status"]))
    return False


def regenerate_subtitles(segments: dict, file_path: str):
    subs = pysrt.SubRipFile()
    for segment in segments:
        sub = pysrt.SubRipItem()
        sub.index = int(segment["index"])  # if "index" in segment else int(segment["id"])
        sub.position = segment["position"]  # if "position" in segment else
        sub.text = segment["text"]
        try:
            sub.start.hours = segment["start"].hour
            sub.start.minutes = segment["start"].minute
            sub.start.seconds = segment["start"].second
            sub.start.milliseconds = segment["start"].microsecond // 1000
            sub.end.hours = segment["end"].hour
            sub.end.minutes = segment["end"].minute
            sub.end.seconds = segment["end"].second
            sub.end.milliseconds = segment["end"].microsecond // 1000
        except:
            sub.start = segment["start"]
            sub.end = segment["end"]
        subs.append(sub)
    subs.save(file_path, encoding="utf-8")
    return file_path


def get_sentences_from_subtitles(source_subtitles):
    sentence_indexed_subtitles = []
    sentence_idx = 0
    sub_idx = 1

    for idx, subtitle_ in enumerate(source_subtitles):
        current_text = subtitle_.text.replace("\n", " ")
        sentences = sent_tokenize(current_text)

        # Calculate the total duration of the subtitle in miliseconds
        total_duration = (subtitle_.end - subtitle_.start).seconds * 1000 + (subtitle_.end - subtitle_.start).milliseconds

        # If there's more than one sentence in the subtitle, divide the time
        if len(sentences) > 1:
            total_chars = sum(len(sentence) for sentence in sentences)
            elapsed_time = 0

            subtitles = []
            for i, sentence in enumerate(sentences):
                proportion = float(len(sentence)) / total_chars

                # Calculate start and end times for the sentence
                elapsed_times_seconds, elapsed_times_milliseconds = divmod(elapsed_time, 1000)
                start_time = subtitle_.start + pysrt.SubRipTime(0, 0, int(elapsed_times_seconds), int(elapsed_times_milliseconds))

                end_time_seconds, end_time_milliseconds = divmod(total_duration * proportion, 1000)
                end_time = start_time + pysrt.SubRipTime(0, 0, int(end_time_seconds), int(end_time_milliseconds))

                # Update the elapsed time
                elapsed_time += total_duration * proportion

                # Create a new subtitle for the sentence
                new_subtitle = pysrt.SubRipItem(start=start_time, end=end_time, text=sentence)
                subtitles.append(new_subtitle)
        else:
            subtitles = [subtitle_]
        # subtitles = [subtitle_]
        for subtitle in subtitles:
            text = subtitle.text.replace("\n", " ")
            # Check if the current text forms a complete sentence with the previous text
            if text.endswith(".") or text.endswith("!") or text.endswith("?"):
                sentence_indexed_subtitles.append(
                    {
                        "start": datetime(2020, 1, 1, subtitle.start.hours, subtitle.start.minutes, subtitle.start.seconds, subtitle.start.milliseconds * 1000),
                        "end": datetime(2020, 1, 1, subtitle.end.hours, subtitle.end.minutes, subtitle.end.seconds, subtitle.end.milliseconds * 1000),
                        "text": text,
                        "id": sentence_idx,
                        "position": subtitle.position,
                        "index": sub_idx,  # subtitle.index
                    }
                )
                previous_text = ""
                sentence_idx += 1
            else:
                sentence_indexed_subtitles.append(
                    {
                        "start": datetime(2020, 1, 1, subtitle.start.hours, subtitle.start.minutes, subtitle.start.seconds, subtitle.start.milliseconds * 1000),
                        "end": datetime(2020, 1, 1, subtitle.end.hours, subtitle.end.minutes, subtitle.end.seconds, subtitle.end.milliseconds * 1000),
                        "text": text,
                        "id": sentence_idx,
                        "position": subtitle.position,
                        "index": sub_idx,  # subtitle.index
                    }
                )
                previous_text = text
            sub_idx += 1

    return sentence_indexed_subtitles


def subtitles_to_sentences(sentence_indexed_subtitles):
    sentences = {}
    for subtitle in sentence_indexed_subtitles:
        if subtitle["id"] not in sentences:
            sentences[subtitle["id"]] = []
        sentences[subtitle["id"]].append(subtitle["text"])
    # join the sentences by space
    sentences = {k: " ".join(v) for k, v in sentences.items()}
    return sentences


def translate(sentences, source_lang, target_lang):
    prompt = """
    Translate the following sentences from {} to {}. Ensure the translations retain the context of the entire document such that these are content of videos from yoga challenges.
    The translated sentences should not be longer than the originals but can be shorter. Here is the list of sentences to translate:
    {}

    Your response mut be in the same format as the input nothing more nothing less.
    """.format(
        id2lang[source_lang], target_lang, json.dumps(sentences, indent=4)
    )
    return_translations = None
    n_try = 1
    model_parameters = {"max_tokens": 2000, "temperature": 0}
    while n_try <= 3:
        try:
            app_logger.info(f"Try number {n_try}")
            translation = chatgpt_model.run(
                [
                    {"role": "user", "content": prompt},
                ],
                parameters=model_parameters,
            )  # You can input text, a public URL or provide a file path on your local machine
            translations = json.loads(translation["data"])
            # convert the indexes to int
            return_translations = {int(k): v for k, v in translations.items()}
        except:
            n_try += 1
            # increase the temperature
            model_parameters["temperature"] += 0.1
            if n_try == 4:
                raise Exception("Translation failed")
            continue
        break
    return return_translations


def from_sentence_to_srt_splits(sentence, translation_splits):
    tmp_sentences = sentence.split(",")
    tmp_splits = deepcopy(translation_splits)
    if len(tmp_splits) == len(tmp_sentences):
        for i, subtitle in enumerate(tmp_splits):
            subtitle["text"] = tmp_sentences[i]
        return_splits = tmp_splits
    else:

        new_combined_subtitles = []
        for sub in translation_splits:
            new_combined_subtitles.append(
                {
                    "start": sub["start"].strftime("%H:%M:%S,%f")[:-3],
                    "end": sub["end"].strftime("%H:%M:%S,%f")[:-3],
                    "text": sub["text"],
                    "index": sub["index"],
                    "id": sub["id"],
                }
            )
        prompt = """
        The folowing are the srt splits for the video. please assign this sentence to this splits while keeping the other params like start, end, index and id as same. the number of splits must be the same
        {}
        You new sentence is : '{}'
        Your response must be in the same format as the input srt splits more nothing less.
        """.format(
            json.dumps(new_combined_subtitles, indent=4), sentence
        )
        model_parameters = {"max_tokens": 2000, "temperature": 0}
        n_try = 1
        return_splits = None
        while n_try <= 3:
            try:
                app_logger.info(f"Try number {n_try}")
                response = chatgpt_model.run(
                    [
                        {"role": "user", "content": prompt},
                    ],
                    parameters=model_parameters,
                )  # You can input text, a public URL or provide a file path on your local machine
                tmp_splits = json.loads(response["data"])
                # revert the time format
                for i, subtitle in enumerate(tmp_splits):
                    tmp_splits[i]["start"] = pysrt.SubRipTime.from_string(subtitle["start"])
                    tmp_splits[i]["end"] = pysrt.SubRipTime.from_string(subtitle["end"])
                return_splits = tmp_splits
            except:
                n_try += 1
                # increase the temperature
                model_parameters["temperature"] += 0.1
                if n_try == 4:
                    raise Exception("Translation failed")
                continue
            break
        assert len(translation_splits) == len(return_splits), "Number of splits do not match"
    return return_splits


def all_sentences_to_srt_splits(translations, sentence_indexed_subtitles):
    processed_subtitles = []
    for id, sentence in translations.items():
        tmp_subtitles = [subtitle for subtitle in sentence_indexed_subtitles if subtitle["id"] == int(id)]

        new_splits = from_sentence_to_srt_splits(sentence, tmp_subtitles)

        processed_subtitles.extend(new_splits)
    return processed_subtitles


# def save_processed_subtitles(processed_subtitles, path_to_subtitles, target_lang):
#     # write the new subtitles using pysrt

#     new_srt = pysrt.SubRipFile()
#     id = 1
#     for subtitle in processed_subtitles:

#         new_srt.append(pysrt.SubRipItem(
#             index=id,
#             start=subtitle['start'],
#             end=subtitle['end'],
#             text=subtitle['text']
#         ))
#         id += 1
#     try:
#         new_srt.save(path_to_subtitles / f"{target_lang}.srt", encoding='utf-8')
#         return True
#     except:
#         return False


def group_by_id(sentence_indexed_subtitles):
    sentences = {}
    for subtitle in sentence_indexed_subtitles:
        if subtitle["id"] not in sentences:
            sentences[subtitle["id"]] = []
        sentences[subtitle["id"]].append(subtitle)
    return list(sentences.values())


def ungroup(subtitles_grouped):
    subs = []
    for group in subtitles_grouped:
        subs.extend(group)
    return subs


# ["de","nl","pt","es","ru","pl","it","ko","ja","zh","cs","et","hi","hu","kn","ml","sv","ta","te","uk"]
id2lang = {
    "en": "English",
    "de": "German",
    "nl": "Dutch",
    "pt": "Portuguese",
    "es": "Spanish",
    "ru": "Russian",
    "pl": "Polish",
    "it": "Italian",
    "ko": "Korean",
    "ja": "Japanese",
    "zh": "Chinese",
    "cs": "Czech",
    "et": "Estonian",
    "hi": "Hindi",
    "hu": "Hungarian",
    "kn": "Kannada",
    "ml": "Malayalam",
    "sv": "Swedish",
    "ta": "Tamil",
    "te": "Telugu",
    "uk": "Ukrainian",
}

lang2id = {v: k for k, v in id2lang.items()}


class MyDefaultDict(dict):
    """Implementation of perl's autovivification feature."""

    def __getitem__(self, item):
        try:
            return dict.__getitem__(self, item)
        except KeyError:
            value = self[item] = type(self)()
            return value

    @classmethod
    def from_dict(cls, source_dict: dict):
        """Create a MyDefaultDict instance from a normal dictionary."""
        my_default_dict = cls()
        for key, value in source_dict.items():
            if isinstance(value, dict):
                my_default_dict[key] = cls.from_dict(value)
            else:
                my_default_dict[key] = value
        return my_default_dict
