import { useCallback, useEffect, useRef, useState } from 'react';

const TARGET_SAMPLE_RATE = 16000;

function downsampleTo16kPCM(float32Samples, inputRate) {
  let samples = float32Samples;
  if (inputRate !== TARGET_SAMPLE_RATE) {
    const ratio = inputRate / TARGET_SAMPLE_RATE;
    const outputLength = Math.max(1, Math.floor(float32Samples.length / ratio));
    const result = new Float32Array(outputLength);
    for (let i = 0; i < outputLength; i++) {
      const idx = Math.min(Math.floor(i * ratio), float32Samples.length - 1);
      result[i] = float32Samples[idx];
    }
    samples = result;
  }

  const pcm16 = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i++) {
    const clamped = Math.max(-1, Math.min(1, samples[i]));
    pcm16[i] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
  }
  return pcm16.buffer;
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  const chunkSize = 0x8000;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
  }
  return btoa(binary);
}

function base64ToInt16Array(base64) {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return new Int16Array(bytes.buffer, 0, Math.floor(bytes.byteLength / 2));
}

export function useVoiceSocket(sessionId, { onCartUpdate } = {}) {
  const [status, setStatus] = useState('disconnected'); // disconnected | connecting | connected
  const [isRecording, setIsRecording] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const [messages, setMessages] = useState([]);
  const [error, setError] = useState(null);
  const [audioLevel, setAudioLevel] = useState(0);

  const wsRef = useRef(null);
  const onCartUpdateRef = useRef(onCartUpdate);
  onCartUpdateRef.current = onCartUpdate;

  // Capture refs
  const micStreamRef = useRef(null);
  const captureCtxRef = useRef(null);
  const processorRef = useRef(null);
  const analyserRef = useRef(null);

  // Playback refs
  const playbackCtxRef = useRef(null);
  const nextPlayTimeRef = useRef(0);
  const activeSourcesRef = useRef([]);

  const appendMessage = useCallback((role, text) => {
    if (!text) return;
    setMessages((prev) => [
      ...prev,
      {
        id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
        role,
        text,
        timestamp: new Date().toLocaleTimeString(),
      },
    ]);
  }, []);

  const stopPlayback = useCallback(() => {
    activeSourcesRef.current.forEach((src) => {
      try {
        src.stop();
      } catch {
        // already stopped
      }
    });
    activeSourcesRef.current = [];
    nextPlayTimeRef.current = 0;
    setIsSpeaking(false);
    setIsPaused(false);
  }, []);

  const enqueueTTSChunk = useCallback((base64Data) => {
    if (!base64Data) return;
    if (!playbackCtxRef.current || playbackCtxRef.current.state === 'closed') {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      playbackCtxRef.current = new AudioCtx({ sampleRate: TARGET_SAMPLE_RATE });
      nextPlayTimeRef.current = 0;
    }

    const ctx = playbackCtxRef.current;
    if (ctx.state === 'suspended') {
      ctx.resume().catch(() => {});
    }

    const pcm16 = base64ToInt16Array(base64Data);
    if (pcm16.length === 0) return;

    const float32 = new Float32Array(pcm16.length);
    for (let i = 0; i < pcm16.length; i++) {
      float32[i] = pcm16[i] / 32768.0;
    }

    const audioBuffer = ctx.createBuffer(1, float32.length, TARGET_SAMPLE_RATE);
    audioBuffer.getChannelData(0).set(float32);

    const source = ctx.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(ctx.destination);

    const startTime = Math.max(ctx.currentTime + 0.02, nextPlayTimeRef.current);
    source.start(startTime);
    nextPlayTimeRef.current = startTime + audioBuffer.duration;
    setIsSpeaking(true);

    activeSourcesRef.current.push(source);
    source.onended = () => {
      activeSourcesRef.current = activeSourcesRef.current.filter((s) => s !== source);
      if (activeSourcesRef.current.length === 0) {
        setIsSpeaking(false);
      }
    };
  }, []);

  const sendPayload = useCallback((payload) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(payload));
      return true;
    }
    return false;
  }, []);

  const connect = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) return;

    const envUrl = import.meta.env.VITE_WS_URL;
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = envUrl
      ? `${envUrl.replace(/\/$/, '')}/ws/voice/${sessionId}`
      : `${protocol}//${window.location.host}/ws/voice/${sessionId}`;

    setStatus('connecting');
    setError(null);

    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      setStatus('connected');
      appendMessage('system', 'Connected to VoiceServe AI');
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        switch (msg.type) {
          case 'transcript':
            if (msg.is_final) appendMessage('user', msg.text);
            break;
          case 'llm_response':
            appendMessage('assistant', msg.text);
            break;
          case 'tts_audio':
            if (msg.data) {
              enqueueTTSChunk(msg.data);
            }
            if (msg.is_final && activeSourcesRef.current.length === 0) {
              setIsSpeaking(false);
            }
            break;
          case 'cart_update':
            if (msg.cart && onCartUpdateRef.current) {
              onCartUpdateRef.current(msg.cart);
            }
            break;
          case 'paused':
            setIsPaused(true);
            break;
          case 'resumed':
            setIsPaused(false);
            break;
          case 'error':
            setError(msg.message || 'Voice session error');
            break;
          default:
            break;
        }
      } catch {
        // ignore malformed frames
      }
    };

    ws.onerror = () => {
      setError('WebSocket connection error. Verify the backend is running.');
    };

    ws.onclose = () => {
      setStatus('disconnected');
      setIsRecording(false);
      stopPlayback();
    };
  }, [sessionId, appendMessage, enqueueTTSChunk, stopPlayback]);

  const stopRecording = useCallback(() => {
    if (processorRef.current) {
      processorRef.current.disconnect();
      processorRef.current = null;
    }
    if (captureCtxRef.current) {
      captureCtxRef.current.close().catch(() => {});
      captureCtxRef.current = null;
    }
    if (micStreamRef.current) {
      micStreamRef.current.getTracks().forEach((t) => t.stop());
      micStreamRef.current = null;
    }
    analyserRef.current = null;
    setIsRecording(false);
    setAudioLevel(0);
    sendPayload({ type: 'end_of_speech' });
  }, [sendPayload]);

  const startRecording = useCallback(async () => {
    setError(null);
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      connect();
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
        },
      });
      micStreamRef.current = stream;

      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      const ctx = new AudioCtx();
      captureCtxRef.current = ctx;

      const source = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;
      analyserRef.current = analyser;

      const processor = ctx.createScriptProcessor(2048, 1, 1);
      processorRef.current = processor;

      processor.onaudioprocess = (e) => {
        const input = e.inputBuffer.getChannelData(0);
        let sumSq = 0;
        for (let i = 0; i < input.length; i++) {
          sumSq += input[i] * input[i];
        }
        const rms = Math.sqrt(sumSq / input.length);
        setAudioLevel(Math.min(1, rms * 5));

        const pcmBuffer = downsampleTo16kPCM(input, ctx.sampleRate);
        const b64 = arrayBufferToBase64(pcmBuffer);
        sendPayload({ type: 'audio_chunk', data: b64 });
      };

      source.connect(analyser);
      analyser.connect(processor);
      processor.connect(ctx.destination);
      setIsRecording(true);
    } catch (err) {
      setError(`Microphone access denied or unavailable: ${err.message}`);
    }
  }, [connect, sendPayload]);

  const interrupt = useCallback(() => {
    stopPlayback();
    sendPayload({ type: 'interrupt' });
  }, [sendPayload, stopPlayback]);

  const togglePause = useCallback(() => {
    if (isPaused) {
      playbackCtxRef.current?.resume().catch(() => {});
      sendPayload({ type: 'resume' });
      setIsPaused(false);
    } else {
      playbackCtxRef.current?.suspend().catch(() => {});
      sendPayload({ type: 'pause' });
      setIsPaused(true);
    }
  }, [isPaused, sendPayload]);

  const sendText = useCallback(
    (text) => {
      if (!text.trim()) return;
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
        setError('Connect voice session first to send messages.');
        return;
      }
      sendPayload({ type: 'text_input', text: text.trim() });
    },
    [sendPayload]
  );

  const disconnect = useCallback(() => {
    stopRecording();
    stopPlayback();
    wsRef.current?.close();
    wsRef.current = null;
  }, [stopPlayback, stopRecording]);

  useEffect(() => {
    connect();
    const pingTimer = setInterval(() => {
      sendPayload({ type: 'ping' });
    }, 25000);

    return () => {
      clearInterval(pingTimer);
      disconnect();
    };
  }, [connect, disconnect, sendPayload]);

  return {
    status,
    isRecording,
    isSpeaking,
    isPaused,
    messages,
    error,
    audioLevel,
    analyserRef,
    connect,
    disconnect,
    startRecording,
    stopRecording,
    interrupt,
    togglePause,
    sendText,
  };
}
