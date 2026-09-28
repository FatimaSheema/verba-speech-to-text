import os
import json
import asyncio
import threading

from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

from aiortc import RTCPeerConnection, RTCSessionDescription
from av import AudioResampler

from deepgram import DeepgramClient
from deepgram.core.events import EventType
from deepgram.listen.v1.types import ListenV1Results


# ==========================================
# LOAD ENVIRONMENT VARIABLES
# ==========================================

load_dotenv()

API_KEY = os.getenv("DEEPGRAM_API_KEY")

if not API_KEY:
    raise ValueError(
        "DEEPGRAM_API_KEY is missing from your .env file."
    )


# ==========================================
# FLASK APP
# ==========================================

app = Flask(__name__)
CORS(app)


# ==========================================
# DEEPGRAM CLIENT
# ==========================================

deepgram = DeepgramClient(api_key=API_KEY)


# ==========================================
# ASYNCIO EVENT LOOP
# ==========================================

loop = asyncio.new_event_loop()


def start_loop():
    """
    Keep an asyncio event loop running
    for WebRTC connections.
    """

    asyncio.set_event_loop(loop)
    loop.run_forever()


threading.Thread(
    target=start_loop,
    daemon=True
).start()


# ==========================================
# HOME PAGE
# ==========================================

@app.route("/")
def home():
    return render_template("index.html")


# ==========================================
# WEBRTC OFFER
# ==========================================

@app.route("/offer", methods=["POST"])
def offer():

    try:

        data = request.json

        if not data:
            return jsonify({
                "error": "No WebRTC offer received."
            }), 400


        remote_offer = RTCSessionDescription(
            sdp=data["sdp"],
            type=data["type"]
        )


        # Create WebRTC connection inside
        # our asyncio event loop
        future = asyncio.run_coroutine_threadsafe(
            create_connection(remote_offer),
            loop
        )


        result = future.result(timeout=15)


        return jsonify(result)


    except Exception as e:

        print("WEBRTC ERROR:", e)

        return jsonify({
            "error": str(e)
        }), 500


# ==========================================
# CREATE WEBRTC CONNECTION
# ==========================================

async def create_connection(remote_offer):

    pc = RTCPeerConnection()


    # This will hold the browser's
    # transcript DataChannel
    transcript_channel = {
        "channel": None
    }


    # ======================================
    # DATA CHANNEL
    # ======================================

    @pc.on("datachannel")
    def on_datachannel(channel):

        print(
            "Data channel received:",
            channel.label
        )


        if channel.label == "transcript":

            transcript_channel["channel"] = channel

            print(
                "Transcript data channel ready."
            )


    # ======================================
    # CONNECTION STATE
    # ======================================

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():

        print(
            "WebRTC state:",
            pc.connectionState
        )


        if pc.connectionState in [
            "failed",
            "closed"
        ]:

            await pc.close()


    # ======================================
    # AUDIO TRACK
    # ======================================

    @pc.on("track")
    def on_track(track):

        print(
            "Track received:",
            track.kind
        )


        if track.kind == "audio":

            asyncio.create_task(
                process_audio(
                    track,
                    transcript_channel
                )
            )


    # ======================================
    # SET REMOTE DESCRIPTION
    # ======================================

    await pc.setRemoteDescription(
        remote_offer
    )


    # ======================================
    # CREATE ANSWER
    # ======================================

    answer = await pc.createAnswer()


    await pc.setLocalDescription(
        answer
    )


    print(
        "WebRTC answer created."
    )


    return {
        "sdp": pc.localDescription.sdp,
        "type": pc.localDescription.type
    }


# ==========================================
# PROCESS MICROPHONE AUDIO
# ==========================================

async def process_audio(
    track,
    transcript_channel
):

    print(
        "Starting Deepgram live transcription..."
    )


    # ======================================
    # AUDIO RESAMPLER
    # ======================================

    resampler = AudioResampler(
        format="s16",
        layout="mono",
        rate=16000
    )


    try:

        # ==================================
        # CONNECT TO DEEPGRAM
        # ==================================

        with deepgram.listen.v1.connect(

            model="nova-3",

            language="en-US",

            encoding="linear16",

            sample_rate=16000,

            channels=1,

            interim_results=True,

            smart_format=True,

            endpointing=300

        ) as connection:


            # ==================================
            # DEEPGRAM MESSAGE HANDLER
            # ==================================

            def on_message(message):

                try:

                    if isinstance(
                        message,
                        ListenV1Results
                    ):

                        if (
                            message.channel
                            and
                            message.channel.alternatives
                        ):

                            text = (
                                message
                                .channel
                                .alternatives[0]
                                .transcript
                            )


                            if text:

                                print(
                                    "Transcript:",
                                    text
                                )


                                channel = (
                                    transcript_channel[
                                        "channel"
                                    ]
                                )


                                if (
                                    channel
                                    and
                                    channel.readyState
                                    == "open"
                                ):

                                    payload = json.dumps({

                                        "transcript": text,

                                        "final": getattr(
                                            message,
                                            "is_final",
                                            False
                                        )

                                    })


                                    # Send transcript
                                    # back to browser
                                    loop.call_soon_threadsafe(

                                        channel.send,

                                        payload

                                    )

                except Exception as e:

                    print(
                        "TRANSCRIPT ERROR:",
                        e
                    )


            # ==================================
            # DEEPGRAM ERROR HANDLER
            # ==================================

            def on_error(error):

                print(
                    "Deepgram error:",
                    error
                )


            # ==================================
            # REGISTER EVENTS
            # ==================================

            connection.on(
                EventType.MESSAGE,
                on_message
            )


            connection.on(
                EventType.ERROR,
                on_error
            )


            # ==================================
            # START DEEPGRAM LISTENER
            # ==================================
            #
            # IMPORTANT:
            # This runs in a separate thread.
            # Otherwise it can block our audio loop.
            #

            listener_thread = threading.Thread(

                target=connection.start_listening,

                daemon=True

            )

            listener_thread.start()


            print(
                "Deepgram listener started."
            )

            print(
                "Sending microphone audio..."
            )


            # ==================================
            # RECEIVE WEBRTC AUDIO
            # ==================================

            while True:

                try:

                    frame = await track.recv()


                    # Convert browser audio
                    # to 16kHz mono PCM
                    frames = resampler.resample(
                        frame
                    )


                    if not isinstance(
                        frames,
                        list
                    ):

                        frames = [
                            frames
                        ]


                    # ==================================
                    # SEND AUDIO TO DEEPGRAM
                    # ==================================

                    for audio_frame in frames:

                        audio_bytes = (
                            audio_frame
                            .to_ndarray()
                            .tobytes()
                        )


                        if audio_bytes:

                            connection.send_media(
                                audio_bytes
                            )


                except Exception as e:

                    print(
                        "Audio receiving error:",
                        e
                    )

                    break


    except Exception as e:

        print(
            "AUDIO ERROR:",
            e
        )


# ==========================================
# START SERVER
# ==========================================

if __name__ == "__main__":

    print()
    print("==============================")
    print("        VERBA")
    print("==============================")
    print()
    print(
        "Server running at:"
    )
    print(
        "http://127.0.0.1:5000"
    )
    print()
    print(
        "WebRTC live transcription ready."
    )
    print()


    app.run(

        host="127.0.0.1",

        port=5000,

        debug=True,

        use_reloader=False

    )