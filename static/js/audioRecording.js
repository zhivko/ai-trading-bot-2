// Audio recording and transcription functionality

class AudioRecorder {
    constructor() {
        this.mediaRecorder = null;
        this.audioChunks = [];
        this.isRecording = false;
        this.stream = null;
        this.recordingStartTime = null;
        this.maxRecordingTime = 30000; // 30 seconds max
        this.recordingTimer = null;
    }

    async initialize() {
        try {
            // Request microphone access
            this.stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true
                }
            });

            console.log('🎤 Microphone access granted');
            return true;
        } catch (error) {
            console.error('❌ Error accessing microphone:', error);
            alert('Error accessing microphone. Please ensure you have granted microphone permissions.');
            return false;
        }
    }

    startRecording() {
        if (this.isRecording) {
            console.warn('⚠️ Already recording');
            return false;
        }

        try {
            // Clear previous recording
            this.audioChunks = [];

            // Create MediaRecorder
            this.mediaRecorder = new MediaRecorder(this.stream, {
                mimeType: 'audio/webm;codecs=opus'
            });

            // Set up event handlers
            this.mediaRecorder.ondataavailable = (event) => {
                if (event.data.size > 0) {
                    this.audioChunks.push(event.data);
                }
            };

            this.mediaRecorder.onstop = () => {
                this.handleRecordingStop();
            };

            // Start recording
            this.mediaRecorder.start(1000); // Collect data every second
            this.isRecording = true;
            this.recordingStartTime = Date.now();

            console.log('🎙️ Recording started');

            // Set up auto-stop timer
            this.recordingTimer = setTimeout(() => {
                if (this.isRecording) {
                    console.log('⏰ Auto-stopping recording (max time reached)');
                    this.stopRecording();
                }
            }, this.maxRecordingTime);

            return true;
        } catch (error) {
            console.error('❌ Error starting recording:', error);
            alert('Error starting recording: ' + error.message);
            return false;
        }
    }

    stopRecording() {
        if (!this.isRecording) {
            console.warn('⚠️ Not currently recording');
            return false;
        }

        try {
            this.mediaRecorder.stop();
            this.isRecording = false;

            // Clear auto-stop timer
            if (this.recordingTimer) {
                clearTimeout(this.recordingTimer);
                this.recordingTimer = null;
            }

            console.log('🎙️ Recording stopped');
            return true;
        } catch (error) {
            console.error('❌ Error stopping recording:', error);
            return false;
        }
    }

    async handleRecordingStop() {
        try {
            console.log('📝 Processing recorded audio...');

            // Create audio blob
            const audioBlob = new Blob(this.audioChunks, { type: 'audio/webm' });

            // Create FormData for upload
            const formData = new FormData();
            formData.append('audio_file', audioBlob, 'recording.webm');

            console.log('📤 Sending audio to server for transcription...');

            // Show processing status
            this.updateUIStatus('processing', 'Transcribing audio...');

            // Send to server
            const response = await fetch('/transcribe_audio', {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                throw new Error(`Server error: ${response.status} ${response.statusText}`);
            }

            const result = await response.json();

            if (result.status === 'success') {
                console.log('✅ Transcription successful:', result.transcribed_text);
                this.updateUIStatus('success', result.transcribed_text);
                this.displayTranscriptionResult(result);
            } else {
                throw new Error('Transcription failed');
            }

        } catch (error) {
            console.error('❌ Error processing recording:', error);
            this.updateUIStatus('error', 'Error: ' + error.message);
        }
    }

    updateUIStatus(status, message) {
        const statusElement = document.getElementById('audio-status');
        const recordButton = document.getElementById('record-button');
        const transcriptionResult = document.getElementById('transcription-result');

        if (statusElement) {
            statusElement.textContent = message;
            statusElement.className = `audio-status ${status}`;
        }

        if (recordButton) {
            if (status === 'recording') {
                recordButton.textContent = '⏹️ Stop Recording';
                recordButton.className = 'record-button recording';
            } else {
                recordButton.textContent = '🎤 Start Recording';
                recordButton.className = 'record-button';
            }
        }

        if (transcriptionResult && status !== 'recording') {
            transcriptionResult.style.display = 'block';
        }
    }

    displayTranscriptionResult(result) {
        const resultElement = document.getElementById('transcription-result');
        if (!resultElement) return;

        const transcriptionText = result.transcribed_text || 'No speech detected';
        const language = result.language || 'unknown';
        const confidence = result.confidence ? (result.confidence * 100).toFixed(1) : 'N/A';

        resultElement.innerHTML = `
            <div class="transcription-header">
                <strong>Transcription Result:</strong>
            </div>
            <div class="transcription-text">
                "${transcriptionText}"
            </div>
            <div class="transcription-meta">
                Language: ${language} | Confidence: ${confidence}%
            </div>
        `;

        resultElement.style.display = 'block';

        // Auto-hide after 10 seconds
        setTimeout(() => {
            if (resultElement) {
                resultElement.style.display = 'none';
            }
        }, 10000);
    }

    cleanup() {
        if (this.isRecording) {
            this.stopRecording();
        }

        if (this.stream) {
            this.stream.getTracks().forEach(track => track.stop());
            this.stream = null;
        }

        if (this.recordingTimer) {
            clearTimeout(this.recordingTimer);
            this.recordingTimer = null;
        }

        console.log('🧹 Audio recorder cleaned up');
    }
}

// Global audio recorder instance
let audioRecorder = null;

// Initialize audio recording functionality
function initializeAudioRecording() {
    console.log('🎤 Initializing audio recording functionality...');

    // Create audio recorder instance
    audioRecorder = new AudioRecorder();

    // Set up record button
    const recordButton = document.getElementById('record-button');
    if (recordButton) {
        recordButton.addEventListener('click', async () => {
            if (!audioRecorder) {
                console.error('❌ Audio recorder not initialized');
                return;
            }

            if (audioRecorder.isRecording) {
                // Stop recording
                audioRecorder.stopRecording();
                audioRecorder.updateUIStatus('stopped', 'Recording stopped. Processing...');
            } else {
                // Start recording
                const initialized = await audioRecorder.initialize();
                if (initialized) {
                    const started = audioRecorder.startRecording();
                    if (started) {
                        audioRecorder.updateUIStatus('recording', 'Recording... Click to stop');
                    }
                }
            }
        });
    }

    // Set up cleanup on page unload
    window.addEventListener('beforeunload', () => {
        if (audioRecorder) {
            audioRecorder.cleanup();
        }
    });

    console.log('✅ Audio recording functionality initialized');
}

// Check if browser supports required APIs
function checkAudioSupport() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        console.warn('⚠️ Browser does not support getUserMedia API');
        return false;
    }

    if (!MediaRecorder) {
        console.warn('⚠️ Browser does not support MediaRecorder API');
        return false;
    }

    if (!FormData) {
        console.warn('⚠️ Browser does not support FormData API');
        return false;
    }

    return true;
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    if (checkAudioSupport()) {
        initializeAudioRecording();
    } else {
        console.error('❌ Audio recording not supported in this browser');
        const recordButton = document.getElementById('record-button');
        if (recordButton) {
            recordButton.disabled = true;
            recordButton.textContent = 'Audio Recording Not Supported';
        }
    }
});

// Export for global access
window.AudioRecorder = AudioRecorder;
window.audioRecorder = audioRecorder;
