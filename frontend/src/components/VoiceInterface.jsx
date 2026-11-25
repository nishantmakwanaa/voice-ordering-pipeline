import React, { useEffect, useRef, useState } from 'react';
import { Mic, MicOff, Pause, Play, Send, Square, Volume2 } from 'lucide-react';

export default function VoiceInterface({ voice }) {
  const [textInput, setTextInput] = useState('');
  const canvasRef = useRef(null);
  const feedEndRef = useRef(null);

  useEffect(() => {
    feedEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [voice.messages]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    let animId;

    const render = () => {
      const { width, height } = canvas;
      ctx.clearRect(0, 0, width, height);

      const barCount = 36;
      const gap = 4;
      const barWidth = (width - gap * (barCount - 1)) / barCount;
      const now = Date.now() / 160;

      const freqData = new Uint8Array(barCount);
      if (voice.isRecording && voice.analyserRef.current) {
        voice.analyserRef.current.getByteFrequencyData(freqData);
      }

      for (let i = 0; i < barCount; i++) {
        let amplitude = 0.08;
        if (voice.isRecording) {
          amplitude = Math.max(0.1, (freqData[i] || 0) / 255);
        } else if (voice.isSpeaking && !voice.isPaused) {
          amplitude = 0.25 + 0.55 * Math.abs(Math.sin(now + i * 0.45));
        }
        const barHeight = Math.max(4, amplitude * (height - 16));
        const x = i * (barWidth + gap);
        const y = (height - barHeight) / 2;

        ctx.fillStyle = voice.isRecording
          ? '#10b981'
          : voice.isSpeaking
          ? '#f59e0b'
          : '#334155';
        ctx.beginPath();
        ctx.roundRect(x, y, barWidth, barHeight, 4);
        ctx.fill();
      }

      animId = requestAnimationFrame(render);
    };

    animId = requestAnimationFrame(render);
    return () => cancelAnimationFrame(animId);
  }, [voice.isRecording, voice.isSpeaking, voice.isPaused, voice.analyserRef]);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!textInput.trim()) return;
    voice.sendText(textInput);
    setTextInput('');
  };

  return (
    <section className="panel">
      <div className="panel-header">
        <div className="panel-title">
          <Volume2 size={18} color="#f59e0b" />
          <span>Voice Assistant</span>
        </div>
        <span
          className={`status-badge ${
            voice.isSpeaking
              ? 'speaking'
              : voice.status === 'connected'
              ? 'connected'
              : ''
          }`}
        >
          <span className="status-dot" />
          {voice.isSpeaking
            ? voice.isPaused
              ? 'Paused'
              : 'Speaking'
            : voice.isRecording
            ? 'Listening'
            : voice.status}
        </span>
      </div>

      {voice.error && <div className="error-banner">{voice.error}</div>}

      <div className="waveform-box">
        <canvas
          ref={canvasRef}
          width={420}
          height={92}
          className="waveform-canvas"
        />
      </div>

      <div className="voice-actions">
        {!voice.isRecording ? (
          <button
            type="button"
            className="btn btn-primary"
            onClick={voice.startRecording}
          >
            <Mic size={16} />
            Start Speaking
          </button>
        ) : (
          <button
            type="button"
            className="btn btn-danger"
            onClick={voice.stopRecording}
          >
            <MicOff size={16} />
            Stop &amp; Send
          </button>
        )}

        <button
          type="button"
          className="btn"
          onClick={voice.togglePause}
          disabled={!voice.isSpeaking && !voice.isPaused}
        >
          {voice.isPaused ? <Play size={15} /> : <Pause size={15} />}
          {voice.isPaused ? 'Resume' : 'Pause'}
        </button>

        <button
          type="button"
          className="btn btn-danger"
          onClick={voice.interrupt}
          disabled={!voice.isSpeaking}
        >
          <Square size={14} />
          Interrupt
        </button>

        {voice.status !== 'connected' && (
          <button type="button" className="btn" onClick={voice.connect}>
            Reconnect
          </button>
        )}
      </div>

      <div className="transcript-feed">
        {voice.messages.length === 0 ? (
          <div className="empty-state">
            Click <strong>Start Speaking</strong> or type below to order, e.g.
            &ldquo;I want a spicy burger and fries&rdquo;.
          </div>
        ) : (
          voice.messages.map((m) => (
            <div key={m.id} className={`msg-bubble ${m.role}`}>
              {m.role !== 'system' && (
                <span className="msg-role">
                  {m.role === 'user' ? 'You' : 'VoiceServe'} · {m.timestamp}
                </span>
              )}
              <span>{m.text}</span>
            </div>
          ))
        )}
        <div ref={feedEndRef} />
      </div>

      <form className="text-input-row" onSubmit={handleSubmit}>
        <input
          className="input"
          type="text"
          placeholder="Or type an order message..."
          value={textInput}
          onChange={(e) => setTextInput(e.target.value)}
        />
        <button
          type="submit"
          className="btn btn-primary"
          disabled={voice.status !== 'connected' || !textInput.trim()}
        >
          <Send size={15} />
        </button>
      </form>
    </section>
  );
}
