# Sketch2Vid
This repository is an implementation of converting sketches into lively videos using Google's Veo 3 model.

## Pre-requisites:

1. Google Cloud SDK [(gcloud CLI)](https://cloud.google.com/sdk/docs/install) installed for authentication.
   
   - Go to terminal/command prompt and enter the command: `gcloud init` and choose the project ID.
     
   - Enter the following commandg to set a default login: `gcloud auth application-default login`.

3. Access to Veo 3.
   > **NOTE**
   > Veo 3 is still in limited preview.

## Run the Web App:

1. Clone the repository on your local machine.
2. Navigate to `cd Sketch2Vid` directory.
3. Run `pip install -r requirements.txt` to install the packages.
4. Open `.env` file and configure your `Gemini API key`, `GCP_PROJECT_ID`, `GCP_BUCKET_NAME`.
5. Run `flask run` to start the server.
6. Open `localhost:5000` on your web browser and enjoy converting your sketches into realistic videos with audio effects.

## Results:
<img src="https://github.com/NSTiwari/Sketch2Vid/blob/main/static/images/sketch2video.gif"/>
