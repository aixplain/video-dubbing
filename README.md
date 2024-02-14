# AIXPLAIN : Generating Dubbed Videos

## **Step 1: Prerequisites**

- Python 3.6 or higher installed on your system
- aiXplain SDK installed and configured as described in the **[aiXplain SDK documentation](https://github.com/aixplain/aiXplain#getting-started)** (More details below)

#### Details:
Prior to running the code, you will need to set up the following services to set up the repo:
- **[aiXplain](https://platform.aixplain.com/)**: For generating dubbed videos, Subtitling pipeline and translation model is accessed from the aiXplain platform. This repo makes use of the aixplain platform and its models and pipeline as an essential element. aiXplain provides easy to use no-code AI/ ML solutions to integrate into applications such as this. They can be easily integrated into applications with a single API call. 

    To use the aiXplain tools, you firstly need to create an account on the aiXplain platform. Then, you can choose from the plethora of models to use directly or create pipelines that use those models in a cascade. Trying or deploying those models requires credits, which may be easily purchased from the platform. 
    
    After setting up, you need to generate a private TEAM_API_KEY from the integrations settings. Please store that safely as it will be used by the aiXplain SDK to securely access your account and models/ pipelines.
    
    Following are some short youtube videos that explain the aiXplain platform and how to use it:
    * **[aiXplain Teaser](https://www.youtube.com/watch?v=lDIe0kA-DJ8)**: Overview 
    * **[aiXplain Tools](https://www.youtube.com/watch?v=A7MuD8W_Qkw)**: Tools overview such as models, piplines, benchmark and finetune. 
    * **[aiXplain Discover](https://www.youtube.com/watch?v=H6_gmsCE4vM)**: Find and try over 38,000 models hosted on the platform 
    * **[aiXplain Credits](https://www.youtube.com/watch?v=X5EYqXDKb3I)**: How to purchase and use credits

After both are set up, you should enter the relevant information and credentials in the environment files:
1. Configure two environment files: **`vars.env`** and **`secrets.env`**.
2. Open the **`vars.env`** file and add the following environment variables:
    - **`SUBTITLE_PIPELINE_ID`** (Optional): The ID of the subtitle pipeline you want to use. If this is not entered, the default subtitling pipeline (English) in the file `subtitle-pipeline.json` will be used. However, you may also create your own pipeline in the `Design` section of the platform. Or modify the existing one (e.g. to use for languages other than English) by uploading the subtitle-pipeline.json file there (Open > Open JSON). Once you save the pipeline, you can use its ID for this variable.
    - **`LOG_LEVEL`**: The log level for the script. The available options are: **`DEBUG`**, **`INFO`**, **`WARNING`**, **`ERROR`**, **`CRITICAL`**.
    This file will be available to you.
3. Open the **`secrets.env`** file and add the following environment variables:
    - **`TEAM_API_KEY`**: aiXplain Platform API key. (Generated from aiXplain platform from Team Settings > Integrations)

    Make sure to replace the values with your desired configuration. Save the files after adding the environment variables. We will proveide an example **`secrets.env.example`** file for you. Please make sure to rename it to **`secrets.env`** and add the values.

## **Step 2: Environment Setup**

1. Clone the repository that contains the script and navigate to the project directory.
2. Install the required Python packages by running the following command:

    ```bash
    conda env create --file conda.yaml
    ```

## Video Dubbing WebApp

To Generate dubbed videos of an given video file, an interactive streamlit web app is provided. You can use the webapp to generate the subtitles and dubbed videos. Please follow the steps below:

### How to run the webapp:

While in the project directory, run:

`python -m streamlit run ./src/web_app/🏠_Home.py --server.port 8507`

Here you may change the server port to any open port of your choice. Login to begin using the Annotator app. Only pre-authorized users will be able to log in. 

### Flow

You may start a new job or choose a previously started job. Each job has a separate folder that stores the relevant data.

**Subtitling**: The app allows you to `upload a video file` directly. Alternatively, you can also provide a `public Dropbox link` to the video file starting with "**[https://www.dropbox.com](https://www.dropbox.com/)**". The app will automatically download the video from Dropbox. The processing starts by uploading file to S3 in specified bucket and folder, and generating subtitles for the source video using the selected aiXplain pipeline. The subtitle pipeline is triggered and run asynchronously, the status of which reflects in the app. 

**Subtitle translation**: Once, subtitles are generated, based on the user choice, the subtitles are then translated to the target language using the `ChatGPT` model from the `aiXplain` platform. As a recent advancement in the domain of Large Language Models, ChatGPT has demonstrated exceptional performance in translation tasks when provided with well-crafted prompts. It also offers the capability to incorporate supplementary contextual information into the prompts, thereby enhancing the quality of the translation.

**Post-editing**: After the translations are generated, the User Interface also provides the ability of post editing the translations manually as well as changing the speed of the synthesized audios based on user preference. 


**Rendering video and Editing audio**: We have multiple number of voices for each language. You can select the voice by selecting the corresponding number and listen to a sample. Optionally, you may check the `samples` directory for the example recordings of each voice. Each recoring is named by the letter of the voice. For example, `A.mp3` is the recording of voice `A`. Clicking `Render Video` triggers the video rendering which may be downloaded after completion.

If you want to change `audio speed`, the video should have been rendered at least once. After the video is first rendered, the synthesized audios become visible and ready to be edited.


### Suported languages
The subtitling pipeline on the platform supports the following languages. By default, the pipeline uses English. If you require choosing a source language other than English, you may create your own pipeline (as mentioned in vars.env > SUBTITLE_PIPELINE_ID section above) and choose the desired language.

- [x] CHINESE
- [x] CZECH
- [x] DUTCH
- [x] ENGLISH
- [ ] ESTONIAN
- [x] GERMAN
- [x] HINDI
- [x] HUNGARIAN
- [x] ITALIAN
- [x] JAPANESE
- [x] KANNADA
- [x] KOREAN
- [x] MALAYALAM
- [x] POLISH
- [x] PORTUGUESE
- [x] RUSSIAN
- [x] SPANISH
- [x] SWEDISH
- [x] TAMIL
- [x] TELUGU
- [x] UKRAINIAN


### **App Behavior**

The app performs the following actions:

1. Uploads the video file to the specified S3 bucket and folder.
2. Runs the subtitle pipeline on the uploaded video using aiXplain SDK.
3. Downloads the generated subtitles in the SRT format for each language available in the result.
4. Saves the downloaded subtitles in the **`subtitles`** directory under a unique `job ID` within the project's data directory.

During the execution of the script, log messages will be displayed in the console, providing information about the progress and status of the pipeline.

Note: The script uses a unique job ID for each run, which helps organize the data and log files generated by the script.

That's it! You have successfully run the script to generate subtitles for a video. The downloaded subtitles can be found in the specified **`subtitles`** directory under the respective job ID.


During the execution of the script, log messages will be displayed in the console, providing information about the progress and status of the subtitling pipeline. Once the subtitling is complete, the generated subtitles are downloaded in the SRT format for the source language. Then the downloaded subtitles are saved in the **`subtitles`** directory under a unique `job ID` within the project's data directory. 

Note: The script uses a unique job ID for each run, which helps organize the data and log files generated by the script.

That's it! You have successfully run the script to generate subtitles for a video. The downloaded subtitles can be found in the specified **`subtitles`** directory under the respective job ID. Following that, the app:

1. Asks for the voice selection.
2. Loads the subtitles from the specified job folder and target language.
3. Connects the subtitle segments to form continuous sequences.
4. Calculates the words per minute (wpm) for each subtitle segment.
5. Adjusts the duration of the subtitle segments to match the desired speaking rate.
6. Synthesizes audio for each subtitle segment using the selected voice model.
7. Combines the synthesized audio segments into a single audio file.
8. Generates a dubbed video by combining the original video with the synthesized audio.
9. Saves the dubbed video and the audio file in the specified output folder.


That's it! You have successfully run the app to generate a dubbed video. The output video and audio files can be found in the specified output folder.