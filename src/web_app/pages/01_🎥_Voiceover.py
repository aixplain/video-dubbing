import io
import json
import os
import sys
import tempfile

import pysrt
import streamlit as st


current_file_path = os.path.dirname(os.path.abspath(__file__))
# aapedn 3 parent directories to the path
sys.path.append(os.path.join(current_file_path, "..", "..", ".."))

from dotenv import load_dotenv

from src.logger import root_logger
from src.models import MODELS
from src.paths import paths
from src.utils import (  # noqa; save_processed_subtitles,
    adjust_segment,
    all_sentences_to_srt_splits,
    check_job_status,
    connect_sequences_sentence_based,
    download_subtitles,
    from_sentence_to_srt_splits,
    get_allowed_speeds,
    get_sentences_from_subtitles,
    group_by_id,
    id2lang,
    lang2id,
    load_subtitles,
    MyDefaultDict,
    process_video,
    regenerate_subtitles,
    remove_cutoff_date,
    render_video,
    subtitles_to_sentences,
    translate,
    ungroup,
    update_segment,
)


BASE_DIR = str(paths.PROJECT_ROOT_DIR.resolve())
# load the .env file
load_dotenv(os.path.join(BASE_DIR, "vars.env"), override=True)
load_dotenv(os.path.join(BASE_DIR, "secrets.env"), override=True)  # THIS SHOULD ALWAYS BE BEFORE aixplain import

app_logger = root_logger.getChild("web_app::create_dataset")


def show_segment(original_segment, segment, model_id, target_lang):
    cont = st.container()
    cont.markdown("<hr style='border: 2px dashed #888'>", unsafe_allow_html=True)
    col1, col2, col3, col4 = cont.columns((5, 5, 5, 2))
    original = " ".join([part["text"] for part in original_segment])
    col1.write(original)
    translated = " ".join([part["text"] for part in segment])
    translation_text = col2.text_area("Translation", value=translated, key=f"changed-{segment[0]['id']}", label_visibility="collapsed")
    segment_of_interest = None
    updated_segments = None
    new_speeds = [None] * len(original_segment)
    segments_of_interest = []
    with col3:
        audio = st.checkbox("Show splits with audio", key=f"show-audio-{segment[0]['id']}")

    for idx, (split_original, split_translated) in enumerate(zip(original_segment, segment)):
        if audio:
            cont_2 = st.container()
            cont_2.markdown("---")
            col1_2, col2_2, col3_2, col4_2 = cont_2.columns((5, 5, 5, 2))
            col1_2.write(split_original["text"])
            col2_2.write(split_translated["text"])
        # check if there is a segment.json file
        if st.session_state["segments_json"] is not None:
            # find segmetn that has index same in st.session_state["segments_json"]
            segment_of_interest = [seg for seg in st.session_state["segments_json"] if int(seg["index"]) == int(split_translated["index"])]
            if len(segment_of_interest) > 0:
                segment_of_interest = segment_of_interest[0]
                segments_of_interest.append(segment_of_interest)
                audio_file = segment_of_interest["audio"]
                temp_segment = None
                speed_dict = get_allowed_speeds(segment_of_interest)
                if audio:
                    cont3 = col3_2.container()
                    col31, col32 = cont3.columns((5, 5))
                    new_speed = col31.slider(
                        "Speed",
                        min_value=speed_dict["min_allowed_speed"],
                        max_value=speed_dict["max_allowed_speed"],
                        value=speed_dict["current_speed"],
                        step=1,
                        key=f"speed-{split_translated['index']}",
                    )
                    new_speeds[idx] = new_speed
                    col32.markdown("##")
                    if col32.button("Apply Change", key=f"apply-{split_translated['index']}"):
                        # if updated_segments is None:
                        #     if translation_text != translated:
                        #         updated_segments = from_sentence_to_srt_splits(translation_text, original_segment)
                        # split_translated_updated = updated_segments[idx]
                        # if segment_of_interest["text"] != split_translated["text"]:
                        # segment_of_interest["text"] = split_translated["text"]
                        temp_segment = adjust_segment(segment_of_interest, new_speed, model_id)
                        audio_file = temp_segment["audio"]
                    # listen audio
                    if os.path.exists(audio_file):
                        cont3.audio(audio_file, format="audio/wav")
    if col4.button("Save", key=f"save-{segment[0]['id']}"):
        # if translation_text != translated: #segment["text"]:
        if updated_segments is None:
            # use gpt to chunkify the sentence after update
            updated_segments = from_sentence_to_srt_splits(translation_text, original_segment)
        for i, part in enumerate(segment):
            for key in part:
                if key in updated_segments[i]:
                    part[key] = updated_segments[i][key]

        # segment["text"] = translation_text
        if st.session_state["segments_json"] is not None:
            for idx, (split_original, split_translated, split_translated_updated) in enumerate(zip(original_segment, segment, updated_segments)):
                segment_of_interest = segments_of_interest[idx] if segments_of_interest else None
                # if split_translated_updated["text"] != split_translated["text"]:
                segment_of_interest["text"] = split_translated_updated["text"]
                if segment_of_interest is not None:
                    speed = get_allowed_speeds(segment_of_interest)["current_speed"] if new_speeds[idx] is None else new_speeds[idx]
                    temp_segment = adjust_segment(segment_of_interest, speed, model_id)
                    update_segment(st.session_state["segments_json_file"], temp_segment)
        sub_path = regenerate_subtitles(ungroup(st.session_state["segments"]), st.session_state["segments_file"])
        segments_postedit = load_subtitles(sub_path)
        # segments_postedit = connect_sequences(segments_postedit)
        segments_postedit_text = [s["text"] for s in segments_postedit]
        st.session_state["stats"][st.session_state["job_id"]][target_lang]["postedit"] = segments_postedit_text
        with open(st.session_state["stats_file"], "w") as file:
            json.dump(st.session_state["stats"], file, indent=4)
        st.success("Subtitles updated successfully")
    return True


def add_new_job(job_id, name):
    with open(paths.WEB_APP_DATA_DIR / "jobs.json") as file:
        jobs = json.load(file)

    if job_id in jobs:
        return False
    existing_job_names = [job["name"] for job in jobs.values()]
    if name in existing_job_names:

        i = 1
        while True:
            job_name = f"{name}_{i}"
            i += 1
            if job_name not in existing_job_names:
                break
        name = job_name
        st.warning(f"Job name already exists, renaming to {name}")

    dict_tmp = check_job_status(job_id)
    dict_tmp["name"] = name
    dict_tmp["subtitles_downloaded"] = False
    jobs[job_id] = dict_tmp

    with open(paths.WEB_APP_DATA_DIR / "jobs.json", "w") as file:
        json.dump(jobs, file, indent=4)

    return True


def delete_job(job_id):
    with open(paths.WEB_APP_DATA_DIR / "jobs.json") as file:
        jobs = json.load(file)

    jobs.pop(job_id)

    with open(paths.WEB_APP_DATA_DIR / "jobs.json", "w") as file:
        json.dump(jobs, file, indent=4)

    return True


def get_job_by_name(name):
    with open(paths.WEB_APP_DATA_DIR / "jobs.json") as file:
        jobs = json.load(file)

    for job_id, job in jobs.items():
        if job["name"] == name:
            return job_id

    return None


def get_job_by_id(job_id):
    with open(paths.WEB_APP_DATA_DIR / "jobs.json") as file:
        jobs = json.load(file)

    return jobs[job_id]


def get_jobs():
    # check only folders under BASE_DIR/data exculede the files
    if not os.path.exists(paths.WEB_APP_DATA_DIR / "jobs.json"):
        with open(paths.WEB_APP_DATA_DIR / "jobs.json", "w") as file:
            json.dump({}, file, indent=4)

    with open(paths.WEB_APP_DATA_DIR / "jobs.json") as file:
        jobs = json.load(file)

    return list(jobs.keys())


def update_job(job_id):
    with open(paths.WEB_APP_DATA_DIR / "jobs.json") as file:
        jobs = json.load(file)

    job = jobs[job_id]

    status = check_job_status(job_id)
    job.update(status)

    if job["status"] == "SUCCESS" and not job["subtitles_downloaded"]:
        download = download_subtitles(job_id)
        if download:
            job["subtitles_downloaded"] = True
    jobs[job_id] = job

    with open(paths.WEB_APP_DATA_DIR / "jobs.json", "w") as file:
        json.dump(jobs, file, indent=4)

    return True


def app():

    if "authentication_status" not in st.session_state or not st.session_state["authentication_status"]:
        # forward to the page where the user can login
        st.warning("Please login first")
        st.stop()

    with st.sidebar:
        if st.session_state["authentication_status"]:
            st.write(f'Welcome *{st.session_state["name"]}*')

    if "job_id" not in st.session_state:
        st.session_state["job_id"] = None

    if "segments" not in st.session_state:
        st.session_state["segments"] = None

    if "segments_file" not in st.session_state:
        st.session_state["segments_file"] = None

    if "segments_json" not in st.session_state:
        st.session_state["segments_json"] = None

    if "segments_json_file" not in st.session_state:
        st.session_state["segments_json_file"] = None

    if "pagination" not in st.session_state:
        st.session_state["pagination"] = 1

    if "translated_segments" not in st.session_state:
        st.session_state["translated_segments"] = {}

    if "stats" not in st.session_state:
        stats = MyDefaultDict()
        stats_file = paths.WEB_APP_DATA_DIR / "stats.json"
        if os.path.exists(stats_file):
            with open(stats_file) as file:
                stats = json.load(file)
            stats = MyDefaultDict.from_dict(stats)
            # stats = defaultdict(dict, stats)
        st.session_state["stats"] = stats
        st.session_state["stats_file"] = stats_file

    jobs2names = {}
    for job in get_jobs():
        jobs2names[job] = get_job_by_id(job)["name"]

    names2jobs = {k: v for v, k in jobs2names.items()}

    st.title("Automatic Video Dubbing")

    # there are two options on is to gie a dropbox link and the other is to upload a file
    # delete a job
    todelete = st.sidebar.checkbox("Delete job(s)")
    if todelete:
        jobs2delete = st.sidebar.multiselect("Select job(s) to delete", [jobs2names[j] for j in get_jobs()])
        if st.sidebar.button("Delete"):
            if len(jobs2delete) > 0:
                for job in jobs2delete:
                    delete_job(names2jobs[job])
                st.success("Job(s) deleted successfully")
                st.experimental_rerun()

    selected_job = st.sidebar.selectbox("Select a job", ["Start a new job"] + [jobs2names[j] for j in get_jobs()])
    selected_job_id = names2jobs[selected_job] if selected_job != "Start a new job" else "Start a new job"
    if selected_job_id == "Start a new job":
        is_link = st.radio("Select an option", ("Upload a video file", "Provide a Dropbox link"))
        if is_link == "Upload a video file":
            st.write("Select a video file to generate subtitles for it.")
            video_file = st.file_uploader("Upload a video file", type=["mov", "mp4"])
        elif is_link == "Provide a Dropbox link":
            st.write("Provide a Dropbox link to generate subtitles for it.")
            video_file = st.text_input("Dropbox link")
        else:
            st.error("Please select an option")
            st.stop()

        job_name = st.text_input("Job Name", value="Untitled Job")

        if st.button("Start"):
            st.write("Starting a new job")
            if video_file is None:
                st.error("Please provide a video file")
                st.stop()
            elif isinstance(video_file, str):
                job_id = process_video(video_file)
                st.session_state["job_id"] = job_id
            else:
                with tempfile.TemporaryDirectory() as temp_dir:
                    file_bytes = io.BytesIO(video_file.read()).getvalue()
                    temp_file_path = os.path.join(temp_dir, video_file.name)
                    with open(temp_file_path, "wb") as file:
                        # save the file in the temp dir
                        file.write(file_bytes)
                    job_id = process_video(temp_file_path)
                    st.session_state["job_id"] = job_id
            add_new_job(job_id, job_name)
            st.success(f"Job started successfully with id: {st.session_state['job_id']}")
    else:
        st.session_state["job_id"] = selected_job_id

        # st.write("Rerunning job")
        # st.session_state["job_id"] = process_video(str((paths.JOBS_DIR / selected_job_id / "input.mov").resolve()))
        # add_new_job(st.session_state["job_id"], get_job_by_id(selected_job_id)["name"])
        # st.success("Job started successfully with id: ", st.session_state["job_id"])

        # TODO: UNCOMMENT THIS LATER
        # status = {
        #     "status": "SUCCESS",
        #     "progress": "100%",
        # }

        with open(paths.WEB_APP_DATA_DIR / "jobs.json") as file:
            jobs = json.load(file)

        if jobs[st.session_state["job_id"]]["status"] == "SUCCESS":
            poll_response = jobs[st.session_state["job_id"]]

            status = poll_response["status"]
            completed = poll_response["completed"]
            progress = poll_response["progress"] if "progress" in poll_response else "0%"
            status = {
                "status": status,
                "completed": completed,
                "progress": progress,
            }
        else:
            status = check_job_status(st.session_state["job_id"])

        # check if jobs_subtitle is downloaded if not download
        if status["status"] == "SUCCESS":
            if not get_job_by_id(st.session_state["job_id"])["subtitles_downloaded"]:
                update_job(st.session_state["job_id"])
        if status["status"] == "ERROR":
            st.error("There was an error in the job, Please restart the job")
            st.stop()

        # add a bar
        progress_bar = st.sidebar.progress(int(status["progress"].split("%")[0]), text=f"Progress: {status['progress']}")
        col_, col_refresh = st.sidebar.columns((10, 5))
        if col_refresh.button("Refresh"):
            st.experimental_rerun()
        if status["status"] == "SUCCESS":
            st.sidebar.markdown("---")
            # selectbox for subtitles update and download

            path_to_subtitles = (paths.JOBS_DIR / st.session_state["job_id"]) / "subtitles"
            source_lang = "en"
            source_srt = path_to_subtitles / f"{source_lang}.srt"
            source_subtitles = pysrt.open(source_srt)
            # if "sentence_indexed_subtitles" not in st.session_state:
            sentence_indexed_subtitles = get_sentences_from_subtitles(source_subtitles)
            sentence_indexed_subtitles = connect_sequences_sentence_based(sentence_indexed_subtitles)
            regenerate_subtitles(sentence_indexed_subtitles, source_srt)
            st.session_state["sentence_indexed_subtitles"] = sentence_indexed_subtitles

            # if "sentences" not in st.session_state:
            sentences = subtitles_to_sentences(sentence_indexed_subtitles)
            st.session_state["sentences"] = sentences

            # Generate subtitles for other languages here: ['pl', 'it', 'te', 'cs', 'uk', 'hi', 'ja', 'kn', 'pt', 'es', 'ml', 'ru', 'en', 'nl', 'et', 'sv', 'ta', 'de', 'ko', 'zh', 'hu']

            # remove "en.srt" from the list
            st.sidebar.markdown("### Select a language and voice")
            subtitle_selection_language = st.sidebar.selectbox("Select a Language", [lang for lang in list(id2lang.values()) if lang != "English"])
            # subtitle_selection_language = st.sidebar.selectbox("Select a Language", [id2lang[x.split(".srt")[0]] for x in subtitle_files])
            target_sub_path = path_to_subtitles / f"{lang2id[subtitle_selection_language]}.srt"
            if not os.path.exists(target_sub_path):
                if st.sidebar.button("Generate Translations"):
                    st.sidebar.markdown("#### Generating translations...")
                    translations = translate(st.session_state["sentences"], source_lang=source_lang, target_lang=subtitle_selection_language)
                    processed_subtitles = all_sentences_to_srt_splits(translations, st.session_state["sentence_indexed_subtitles"])
                    for idx, subtitle in enumerate(processed_subtitles):  # manually set index in increasing order
                        subtitle["index"] = idx + 1
                        subtitle["position"] = ""
                    # st.session_state["translated_segments"][lang2id[subtitle_selection_language]] = {"splits": processed_subtitles, "sentence_wise": translations}
                    # subtitle_saved_path = save_processed_subtitles(processed_subtitles, path_to_subtitles, lang2id[subtitle_selection_language])
                    subtitle_saved_path = regenerate_subtitles(processed_subtitles, target_sub_path)
                    #  for writing to stats.json
                    subs_connected = load_subtitles(subtitle_saved_path)
                    subs_connected_text = [s["text"] for s in subs_connected]  # connect_sequences(subs_connected)
                    # if
                    st.session_state["stats"][st.session_state["job_id"]]["job_name"] = jobs2names[st.session_state["job_id"]]
                    st.session_state["stats"][st.session_state["job_id"]][lang2id[subtitle_selection_language]]["translation_orig"] = subs_connected_text
                    with open(st.session_state["stats_file"], "w") as file:
                        json.dump(st.session_state["stats"], file, indent=4)
                    st.sidebar.success("Translations generated successfully!")
                # else:
                #     st.sidebar.warning("Already existing translation will be used.")

            if os.path.exists(target_sub_path):
                subtitle_files = list((paths.JOBS_DIR / st.session_state["job_id"] / "subtitles").glob("*.srt"))
                subtitle_files = sorted([file.name for file in subtitle_files if file.name != "en.srt"])

                st.sidebar.markdown("### Select a gender of the voice")
                gender_selected = st.sidebar.selectbox("Select a Gender", ["Female", "Male"]).lower()
                # select accent
                # accents available in MODELS[gender]
                available_accents = list({v["accent"] for v in MODELS[gender_selected][lang2id[subtitle_selection_language]]["voices"]})
                accent_selected = st.sidebar.selectbox("Select an accent", available_accents)

                if subtitle_selection_language is not None and gender_selected is not None:
                    voice_dir = paths.VOICES_DIR / gender_selected / lang2id[subtitle_selection_language]
                    voices = sorted(list((voice_dir).glob(f"{accent_selected}_*.mp3")))
                    selected_voice = st.sidebar.selectbox("Select a Voice", [voice.name.split(".")[0].split("_")[1] for voice in voices])
                    # for each selected listen to the audio if needed
                    if selected_voice is not None:
                        if not str(st.session_state["segments_json_file"]).endswith(
                            f"{st.session_state['job_id']}/outputs/{gender_selected}/{lang2id[subtitle_selection_language]}/{accent_selected}/segments-{selected_voice}.json"
                        ):
                            st.session_state["segments_json_file"] = str(
                                (
                                    paths.JOBS_DIR
                                    / st.session_state["job_id"]
                                    / "outputs"
                                    / gender_selected
                                    / lang2id[subtitle_selection_language]
                                    / accent_selected
                                    / f"segments-{selected_voice}.json"
                                ).resolve()
                            )
                        if os.path.exists(st.session_state["segments_json_file"]):
                            with open(st.session_state["segments_json_file"]) as file:
                                st.session_state["segments_json"] = json.load(file)
                        else:
                            st.session_state["segments_json"] = None
                        st.sidebar.markdown("**Listen the voice**")
                        st.sidebar.audio(str((voice_dir / f"{accent_selected}_{selected_voice}.mp3").resolve()), format="audio/wav")

                else:
                    st.session_state["segments_json"] = None

                if len(subtitle_files) == 0:
                    st.warning("No subtitles found Even though the job is finished, Please contact the admin")
                if subtitle_selection_language is not None:
                    subtitle_file = paths.JOBS_DIR / st.session_state["job_id"] / "subtitles" / f"{lang2id[subtitle_selection_language]}.srt"
                    # input_subtitle_file = paths.JOBS_DIR / st.session_state["job_id"] / "subtitles" / "en.srt"
                    st.session_state["input_segments"] = st.session_state[
                        "sentence_indexed_subtitles"
                    ]  # load_subtitles(input_subtitle_file) # st.session_state["sentence_indexed_subtitles"] #

                    st.session_state["segments"] = load_subtitles(
                        subtitle_file
                    )  # st.session_state["translated_segments"][lang2id[subtitle_selection_language]]["splits"]#load_subtitles(subtitle_file)
                    # label with sentence id from input subs
                    for ind, sub in enumerate(st.session_state["segments"]):
                        sub["id"] = st.session_state["input_segments"][ind]["id"]

                    st.session_state["input_segments"] = group_by_id(st.session_state["sentence_indexed_subtitles"])
                    st.session_state["segments"] = group_by_id(st.session_state["segments"])

                    st.session_state["segments_file"] = subtitle_file
                    # for each segment show the english subtitle and the translated subtitle and the audio to listen
                    # and a text box to edit the translated subtitle
                    # and a button to save the changes
                    # get pagination from user
                    col_page0, col_page1 = st.columns((15, 2))
                    st.session_state["pagination"] = col_page1.number_input(
                        "Page", min_value=1, max_value=len(st.session_state["segments"]) // 10 + 1, value=st.session_state["pagination"], step=1
                    )
                    st.write(
                        f"Showing {(st.session_state['pagination']-1)*10} to {(st.session_state['pagination'])*10} of {len(st.session_state['segments'])} segments"
                    )
                    # for original_segment, segment in zip(st.session_state["input_segments"], st.session_state["segments"]):
                    colh1, colh2, colh3, colh4 = st.columns((5, 5, 5, 2))
                    colh1.markdown("### Original Text")
                    colh2.markdown("### Translation")
                    colh3.markdown("### Audio")
                    colh4.markdown("### ")

                    sent_id = 0
                    for original_segment, segment in zip(
                        st.session_state["input_segments"][(st.session_state["pagination"] - 1) * 10 : (st.session_state["pagination"]) * 10],
                        st.session_state["segments"][(st.session_state["pagination"] - 1) * 10 : (st.session_state["pagination"]) * 10],
                    ):
                        if selected_voice is not None:
                            model_id = [
                                v
                                for v in MODELS[gender_selected][lang2id[subtitle_selection_language]]["voices"]
                                if v["name"] == selected_voice and v["accent"] == accent_selected
                            ][0]["model_id"]
                            show_segment(original_segment, segment, model_id, lang2id[subtitle_selection_language])
                        sent_id += 1
                if st.session_state["segments_json"] is None:
                    st.sidebar.warning("You must render first to Generate Audios and Listen")
                if subtitle_selection_language is not None and selected_voice is not None and accent_selected is not None and gender_selected is not None:
                    # add a button to RENDER the video
                    # col2.markdown("# Render Video")
                    # select a language to render the video
                    butoncol1, butoncol2 = st.sidebar.columns((5, 5))
                    if butoncol1.button("Render Video"):
                        # create a temp folder
                        with st.spinner(f"Rendering video for {subtitle_selection_language}"):
                            file = render_video(
                                st.session_state["job_id"],
                                lang2id[subtitle_selection_language],
                                gender_selected,
                                accent_selected,
                                selected_voice,
                                overwrite=True,
                            )
                            #
                        st.success("Video rendered successfully")
                    try:
                        file = (
                            paths.JOBS_DIR
                            / st.session_state["job_id"]
                            / "outputs"
                            / gender_selected
                            / lang2id[subtitle_selection_language]
                            / accent_selected
                            / f"{selected_voice}.mp4"
                        )
                        if file.exists():

                            with open(file, "rb") as file:
                                job_id = st.session_state["job_id"]
                                job_name = get_job_by_id(job_id)["name"]
                                butoncol2.download_button(
                                    "Download Video",
                                    file,
                                    f"{job_name}-{subtitle_selection_language}-{gender_selected}_{accent_selected}_{selected_voice}.mp4",
                                    "video/mp4",
                                )

                    except:
                        st.sidebar.error(f"Video not found for {subtitle_selection_language}")


app()
