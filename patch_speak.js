const fs = require('fs');
const file = '/Users/sujayabhat/Downloads/Agentic OS/jatayu/web/static/app.js';
let content = fs.readFileSync(file, 'utf8');

const regex = /async function speakReply\(text\) \{[\s\S]*?\n\}\n/m;
const match = content.match(regex);
if (match) {
    const replacement = `async function speakReply(text) {
    if (typeof _debugLog === 'function') _debugLog("speakReply called. ttsEnabled=" + ttsEnabled);
    if (!ttsEnabled || !text || !text.trim()) {
        if (typeof _debugLog === 'function') _debugLog("speakReply aborted.");
        return;
    }

    setVoiceStatus('🔊 Speaking…', 'speaking');

    try {
        if (typeof _debugLog === 'function') _debugLog("Fetching /api/speak...");
        const resp = await fetch('/api/speak', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text }),
        });
        
        const ttsError = resp.headers.get('X-TTS-Error');
        const audioBlob = resp.ok ? await resp.blob() : null;

        if (typeof _debugLog === 'function') _debugLog("Fetch complete. OK=" + resp.ok + " Size=" + (audioBlob ? audioBlob.size : 'null'));

        // If ElevenLabs returned valid audio, play it
        if (audioBlob && audioBlob.size >= 100) {
            const audioUrl = URL.createObjectURL(audioBlob);
            
            const ttsAudio = document.getElementById('ttsAudio') || new Audio();
            currentAudio = ttsAudio; // keep track so stopTTS() works
            
            if (typeof _debugLog === 'function') _debugLog("Playing audio URL...");
            
            ttsAudio.src = audioUrl;
            ttsAudio.onended = () => {
                if (typeof _debugLog === 'function') _debugLog("Audio ended normally.");
                setVoiceStatus('');
                URL.revokeObjectURL(audioUrl);
                currentAudio = null;
                // Notify BattleGround that audio playback finished
                const bgCtrl = window._battleGroundController;
                if (bgCtrl && bgCtrl._isActive) {
                    bgCtrl.stateMachine.forceState('IDLE');
                    bgCtrl._setTranscript('Click the orb to speak again');
                }
            };
            
            ttsAudio.onerror = (e) => {
                console.error("Audio element error", e);
                if (typeof _debugLog === 'function') _debugLog("Audio onerror fired!");
                setVoiceStatus('');
                URL.revokeObjectURL(audioUrl);
                currentAudio = null;
                // Notify BattleGround on audio error too
                const bgCtrl = window._battleGroundController;
                if (bgCtrl && bgCtrl._isActive) {
                    bgCtrl.stateMachine.forceState('IDLE');
                }
            };

            try {
                await ttsAudio.play();
                if (typeof _debugLog === 'function') _debugLog("Audio started playing!");
                return;
            } catch (playErr) {
                console.error("Audio.play() failed:", playErr);
                if (typeof _debugLog === 'function') _debugLog("play() error: " + playErr.message);
                // Fallback to speech synthesis if autoplay blocks it
                _speakWithBrowserFallback(text);
                return;
            }
        }

        if (typeof _debugLog === 'function') _debugLog("Falling back to browser speech.");
        if (ttsError) console.warn('⚔️ ElevenLabs unavailable:', ttsError, '— using browser speech fallback');
        _speakWithBrowserFallback(text);

    } catch (e) {
        console.error('TTS error:', e);
        if (typeof _debugLog === 'function') _debugLog("Fetch error: " + e.message);
        // Still try browser fallback on network failure
        _speakWithBrowserFallback(text);
    }
}
`;
    content = content.replace(regex, replacement);
    fs.writeFileSync(file, content);
    console.log("Successfully patched speakReply");
} else {
    console.log("Could not find speakReply function!");
}
