const startBtn = document.getElementById("startBtn");
const stopBtn = document.getElementById("stopBtn");
const statusText = document.getElementById("status");
const transcriptText = document.getElementById("transcript");

let peerConnection;
let transcriptChannel;
let microphoneStream;


startBtn.addEventListener("click", startVerba);


async function startVerba() {

    try {

        statusText.textContent = "🎙️ Connecting...";

        microphoneStream =
            await navigator.mediaDevices.getUserMedia({
                audio: true
            });


        peerConnection =
            new RTCPeerConnection();


        // Add microphone to WebRTC
        microphoneStream
            .getTracks()
            .forEach(track => {

                peerConnection.addTrack(
                    track,
                    microphoneStream
                );

            });


        // Create DataChannel for transcripts
        transcriptChannel =
            peerConnection.createDataChannel(
                "transcript"
            );


        transcriptChannel.onopen = () => {

            console.log(
                "Transcript channel connected"
            );

            statusText.textContent =
                "🎙️ Listening...";
        };


        transcriptChannel.onmessage = (event) => {

            const data =
                JSON.parse(event.data);

            console.log(
                "Transcript:",
                data.transcript
            );


            if (data.transcript) {

                transcriptText.textContent =
                    data.transcript;

            }

        };


        transcriptChannel.onerror = (error) => {

            console.error(
                "DataChannel error:",
                error
            );

        };


        // Create WebRTC offer
        const offer =
            await peerConnection.createOffer();


        await peerConnection.setLocalDescription(
            offer
        );


        // Send offer to Python
        const response =
            await fetch("/offer", {

                method: "POST",

                headers: {
                    "Content-Type":
                        "application/json"
                },

                body: JSON.stringify({
                    sdp:
                        peerConnection
                            .localDescription
                            .sdp,

                    type:
                        peerConnection
                            .localDescription
                            .type
                })

            });


        const answer =
            await response.json();


        if (answer.error) {

            throw new Error(
                answer.error
            );

        }


        // Complete WebRTC connection
        await peerConnection.setRemoteDescription(
            answer
        );


        startBtn.disabled = true;
        stopBtn.disabled = false;


    } catch (error) {

        console.error(error);

        statusText.textContent =
            "❌ " + error.message;

    }

}


stopBtn.addEventListener(
    "click",
    stopVerba
);


function stopVerba() {

    if (microphoneStream) {

        microphoneStream
            .getTracks()
            .forEach(track =>
                track.stop()
            );

    }


    if (transcriptChannel) {

        transcriptChannel.close();

    }


    if (peerConnection) {

        peerConnection.close();

    }


    statusText.textContent =
        "Ready";

    startBtn.disabled = false;
    stopBtn.disabled = true;

}