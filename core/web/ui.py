import os
import time
import base64
import asyncio
from datetime import datetime, timedelta
from core.utils.student_id_store import list_sids as _list_known_sids
from aiohttp import web
from config.logger import setup_logging
from core.utils.vllm import create_instance


TAG = __name__


def _html_page(title: str, body: str) -> web.Response:
    head = (
                "<!doctype html>\n"
                "<html lang=\"zh-CN\">\n"
                "<head>\n"
                "  <meta charset=\"utf-8\" />\n"
                "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />\n"
                "  <title>" + title + "</title>\n"
                "  <style>\n"
                "    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, 'Noto Sans', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif; margin: 20px; background-color: #f4f6f9; color: #333; }\n"
                "    a { color: #1677ff; text-decoration: none; transition: fill 0.2s, color 0.2s; }\n"
                "    a:hover { text-decoration: underline; color: #0f5ed7; }\n"
                "    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 20px; }\n"
                "    .card { border: 1px solid #e1e4e8; border-radius: 12px; padding: 20px; background: #fff; box-shadow: 0 2px 8px rgba(0,0,0,0.03); transition: transform 0.25s ease, box-shadow 0.25s ease; }\n"
                "    .card:hover { transform: translateY(-3px); box-shadow: 0 12px 24px rgba(0,0,0,0.06); }\n"
                "    .thumb { width: 100%; height: auto; border-radius: 8px; object-fit: cover; background: #fafafa; border: 1px solid #f0f0f0; margin-bottom: 10px; }\n"
                "    .meta { font-size: 13px; color: #7f8c8d; margin-top: 8px; word-break: break-all; }\n"
                "    header { margin-bottom: 24px; padding-bottom: 12px; border-bottom: 1px solid #eaeaea; display: flex; align-items: baseline; gap: 20px; }\n"
                "    header h2 { margin: 0; font-size: 24px; color: #2c3e50; font-weight: 600; }\n"
                "    header div { font-size: 14px; text-transform: uppercase; font-weight: 500; letter-spacing: 0.5px; }\n"
                "    header a { color: #5c6a79; padding: 4px 8px; border-radius: 4px; transition: background 0.2s; }\n"
                "    header a:hover { text-decoration: none; background: #eef2f5; color: #1677ff; }\n"
                "    form { margin: 16px 0; display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }\n"
                "    input[type=\"text\"], input[type=\"password\"], input[type=\"number\"], select { flex: 1 1 200px; padding: 8px 12px; border: 1px solid #d9d9d9; border-radius: 6px; font-size: 14px; transition: border-color 0.2s, box-shadow 0.2s; outline: none; }\n"
                "    input[type=\"text\"]:focus, select:focus { border-color: #1677ff; box-shadow: 0 0 0 2px rgba(22,119,255,0.2); }\n"
                "    button { padding: 8px 16px; cursor: pointer; font-size: 14px; font-weight: 500; }\n"
                "    .json { white-space: pre-wrap; background: #f8f9fa; padding: 12px; border-radius: 8px; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace; font-size: 12.5px; color: #24292e; border: 1px solid #e1e4e8; }\n"
                "    .btn { display:inline-block; padding: 10px 20px; border-radius: 8px; border: 1px solid transparent; text-decoration: none; line-height: 1.4; font-weight: 500; transition: all 0.2s; cursor: pointer; text-align: center; }\n"
                "    .btn-primary { background: #1677ff; color: #fff; border-color: #1677ff; box-shadow: 0 2px 4px rgba(22,119,255,.15); }\n"
                "    .btn-primary:hover { background: #0f5ed7; border-color: #0f5ed7; text-decoration: none; box-shadow: 0 4px 8px rgba(22,119,255,.25); transform: translateY(-1px); }\n"
                "    .hero { padding: 32px 24px; border-radius: 16px; background: linear-gradient(135deg, #f0f5ff 0%, #ffffff 100%); border: 1px solid #e6f0ff; box-shadow: 0 8px 24px rgba(22,119,255,0.04); position: relative; overflow: hidden; }\n"
                "    .hero::before { content: ''; position: absolute; top: -50px; right: -50px; width: 200px; height: 200px; background: radial-gradient(circle, rgba(22,119,255,0.1) 0%, rgba(255,255,255,0) 70%); border-radius: 50%; pointer-events: none; }\n"
                "    .hero h1 { margin: 0 0 12px; font-size: 32px; color: #1a2b4c; letter-spacing: -0.5px; }\n"
                "    .hero p { margin: 0 0 24px; color:#4a5568; font-size: 15px; max-width: 600px; line-height: 1.6; }\n"
                "    .hero .actions { display:flex; gap:12px; flex-wrap:wrap; align-items:center; }\n"
                "    .btn-outline { background:#fff; color:#1677ff; border-color:#91caff; }\n"
                "    .btn-outline:hover { background:#f0f5ff; border-color: #1677ff; color: #0f5ed7; transform: translateY(-1px); }\n"
                "    .home-quick h3.section-header { margin: 32px 0 16px; font-size: 20px; color: #2c3e50; display: flex; align-items: center; gap: 8px; }\n"
                "    .home-quick .card { display: flex; flex-direction: column; }\n"
                "    .home-quick .card h3 { margin: 0 0 12px; font-size: 18px; color: #2c3e50; border-bottom: 2px solid #f0f5ff; padding-bottom: 10px; }\n"
                "    .home-quick .card p { margin: 0; color:#5c6a79; line-height: 1.6; flex: 1; font-size: 14.5px; }\n"
                "    .home-quick .card .actions { margin-top: 16px; }\n"
                "  </style>\n"
                "  <link rel=\"icon\" href=\"data:,\" />\n"
                "  </head>\n"
                "<body>\n"
        "  <header>\n"
        "    <h2>" + title + "</h2>\n"
    "    <div><a href=\"/web\">首页</a> · <a href=\"/web/vision\">视觉记录</a> · <a href=\"/web/generated\">生成图片</a> · <a href=\"/web/generated/analyze\">生成内容分析</a> · <a href=\"/web/vision/upload\">上传图片分析</a> · <a href=\"/web/conversations\">对话记录</a></div>\n"
        "  </header>\n"
        )
    script = (
        "<script>\n"
        "(function(){\n"
        "  const hasSR = ('webkitSpeechRecognition' in window) || ('SpeechRecognition' in window);\n"
        "  const secureOK = window.isSecureContext || ['localhost','127.0.0.1'].includes(location.hostname);\n"
        "  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;\n"
        "  let micStream = null;\n"
        "  let activeRecog = null;\n"
        "  // 按住说话录音状态\n"
        "  let recCtx = null, recProc = null, recFrames = [], recTargetInput = null;\n"
        "  let recSampleRate = 16000, recStarted = false;\n"
    "  let audioCtx = null;\n"
    "  let analyser = null;\n"
    "  let rafId = 0;\n"
    "  let levelEl = null;\n"
    "  let deviceEl = null;\n"
    "  let deviceSel = null;\n"
    "  let chkEC = null, chkNS = null, chkAGC = null;\n"
    "  // 波形画布\n"
    "  let waveCanvas = null; let waveCtx2d = null;\n"
        "  let holdBtn = null;\n"
        "  function setAnyStatus(t){ try{ const el=document.getElementById('chat-status'); if(el) el.textContent=t; }catch(_){} }\n"
    "  function getRecordSeconds(){ const el=document.getElementById('chat-record-seconds'); const v=Number(el?el.value:3); return (isFinite(v)&&v>0&&v<=30)?v:3; }\n"
    "  function getMaxImages(){ const el=document.getElementById('chat-max-images'); const v=Number(el?el.value:6); return (isFinite(v)&&v>=1&&v<=50)?v:6; }\n"
    "  // 按住录音：开始\n"
    "  async function startHoldRecord(targetInput){\n"
    "    try{ stopAudio(); stopMic(); }catch(_){}\n"
    "    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia){ throw new Error('浏览器不支持麦克风采集'); }\n"
    "    const cons = buildConstraints();\n"
    "    micStream = await navigator.mediaDevices.getUserMedia(cons);\n"
    "    try{ await startLevelMeter(micStream); }catch(_){}\n"
    "    recFrames = []; recTargetInput = targetInput || null; recStarted = true;\n"
    "    recCtx = new (window.AudioContext || window.webkitAudioContext)();\n"
    "    if (recCtx.state === 'suspended'){ try{ await recCtx.resume(); }catch(_){} }\n"
    "    const src = recCtx.createMediaStreamSource(micStream);\n"
    "    recProc = (recCtx.createScriptProcessor ? recCtx.createScriptProcessor(4096, 1, 1) : null);\n"
    "    if (!recProc){ throw new Error('浏览器不支持录音处理'); }\n"
    "    const sampleRate = recCtx.sampleRate; const targetRate = 16000;\n"
    "    recProc.onaudioprocess = (e)=>{\n"
    "      const input = e.inputBuffer.getChannelData(0);\n"
    "      const ratio = sampleRate/targetRate; const len = Math.floor(input.length/ratio);\n"
    "      const out = new Float32Array(len);\n"
    "      for(let i=0;i<len;i++){ out[i] = input[Math.floor(i*ratio)] || 0; }\n"
    "      recFrames.push(out);\n"
    "    };\n"
    "    src.connect(recProc); recProc.connect(recCtx.destination);\n"
    "  }\n"
    "  // 按住录音：结束并上传识别\n"
    "  async function stopHoldRecord(targetInput){\n"
    "    if (!recStarted){ return false; }\n"
    "    recStarted = false;\n"
    "    try{ if (recProc){ recProc.disconnect(); } }catch(_){}\n"
    "    try{ if (recCtx){ recCtx.close(); } }catch(_){}\n"
    "    recProc = null; recCtx = null;\n"
    "    try{ if (micStream){ micStream.getTracks().forEach(t=>t.stop()); } }catch(_){}\n"
    "    const frames = recFrames || []; recFrames = [];\n"
    "    stopAudio(); stopMic();\n"
    "    let totalLen = 0; for(const f of frames){ totalLen += f.length; }\n"
    "    const pcm16 = new Int16Array(totalLen);\n"
    "    let off=0; for(const f of frames){ for(let i=0;i<f.length;i++){ let v=f[i]; v=Math.max(-1, Math.min(1, v)); pcm16[off++] = v<0? v*0x8000 : v*0x7FFF; } }\n"
    "    function wavFromPCM(pcm, sampleRate){\n"
    "      const bytesPerSample = 2; const blockAlign = 1*bytesPerSample; const byteRate = sampleRate*blockAlign;\n"
    "      const dataSize = pcm.length * bytesPerSample;\n"
    "      const buffer = new ArrayBuffer(44 + dataSize);\n"
    "      const view = new DataView(buffer);\n"
    "      function writeStr(o, s){ for(let i=0;i<s.length;i++) view.setUint8(o+i, s.charCodeAt(i)); }\n"
    "      let p=0; writeStr(p, 'RIFF'); p+=4; view.setUint32(p, 36+dataSize, true); p+=4; writeStr(p, 'WAVE'); p+=4; writeStr(p, 'fmt '); p+=4;\n"
    "      view.setUint32(p, 16, true); p+=4; view.setUint16(p, 1, true); p+=2; view.setUint16(p, 1, true); p+=2; view.setUint32(p, sampleRate, true); p+=4;\n"
    "      view.setUint32(p, byteRate, true); p+=4; view.setUint16(p, blockAlign, true); p+=2; view.setUint16(p, 16, true); p+=2; writeStr(p, 'data'); p+=4;\n"
    "      view.setUint32(p, dataSize, true); p+=4;\n"
    "      let o=p; for(let i=0;i<pcm.length;i++,o+=2){ view.setInt16(o, pcm[i], true); }\n"
    "      return new Blob([view], {type:'audio/wav'});\n"
    "    }\n"
    "    const wavBlob = wavFromPCM(pcm16, 16000);\n"
    "    try{ setAnyStatus('上传识别中…'); }catch(_){}\n"
    "    try{\n"
    "      const fd = new FormData(); fd.append('audio', wavBlob, 'audio.wav');\n"
    "      const resp = await fetch('/web/asr/transcribe', { method:'POST', body: fd });\n"
    "      const data = await resp.json().catch(()=>({success:false,message:'解析响应失败'}));\n"
    "      if (data.success && data.text){\n"
    "        const ti = targetInput || recTargetInput;\n"
    "        if (ti){ if (ti.value && !ti.value.endsWith(' ')) ti.value += ' '; ti.value += data.text; }\n"
    "        setAnyStatus('转写成功'); return true;\n"
    "      } else { setAnyStatus('转写失败：' + (data.message || '未知错误')); return false; }\n"
    "    }catch(e){ setAnyStatus('识别异常：' + e); return false; }\n"
    "    finally{ recTargetInput = null; }\n"
    "  }\n"
    "  // 服务器识别（录音->WAV->上传），可选将结果写入 targetInput\n"
    "  async function serverTranscribe(seconds=3, targetInput){\n"
    "    const statusEls = Array.from(document.querySelectorAll('#chat-status')).concat(Array.from(document.querySelectorAll('.meta')));\n"
    "    function setAnyStatus(t){ try{ const el=document.getElementById('chat-status'); if(el) el.textContent=t; }catch(_){} }\n"
    "    setAnyStatus('服务器识别：准备录音…');\n"
    "    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia){ setAnyStatus('浏览器不支持麦克风采集'); return false; }\n"
    "    try{\n"
    "      stopAudio(); stopMic();\n"
    "      const cons = buildConstraints();\n"
    "      micStream = await navigator.mediaDevices.getUserMedia(cons);\n"
    "      const wavBlob = await (async function record(seconds){\n"
    "        const ctx = new (window.AudioContext || window.webkitAudioContext)();\n"
    "        if (ctx.state === 'suspended'){ try{ await ctx.resume(); }catch(_){} }\n"
    "        const src = ctx.createMediaStreamSource(micStream);\n"
    "        const sampleRate = ctx.sampleRate; const targetRate = 16000;\n"
    "        const frames = [];\n"
    "        const proc = (ctx.createScriptProcessor ? ctx.createScriptProcessor(4096, 1, 1) : null);\n"
    "        if (!proc){ throw new Error('浏览器不支持录音处理'); }\n"
    "        src.connect(proc); proc.connect(ctx.destination);\n"
    "        proc.onaudioprocess = (e)=>{\n"
    "          const input = e.inputBuffer.getChannelData(0);\n"
    "          const ratio = sampleRate / targetRate;\n"
    "          const len = Math.floor(input.length / ratio);\n"
    "          const out = new Float32Array(len);\n"
    "          for (let i=0;i<len;i++){ out[i] = input[Math.floor(i*ratio)] || 0; }\n"
    "          frames.push(out);\n"
    "        };\n"
    "        await new Promise(r=> setTimeout(r, Math.max(1200, seconds*1000)) );\n"
    "        proc.disconnect(); src.disconnect();\n"
    "        try{ ctx.close(); }catch(_){}\n"
    "        try{ micStream.getTracks().forEach(t=>t.stop()); }catch(_){ }\n"
    "        let totalLen = frames.reduce((s,a)=>s+a.length, 0);\n"
    "        const pcm16 = new Int16Array(totalLen);\n"
    "        let off=0; for(const f of frames){ for(let i=0;i<f.length;i++){ let v=f[i]; v=Math.max(-1, Math.min(1, v)); pcm16[off++] = v<0? v*0x8000 : v*0x7FFF; }}\n"
    "        function wavFromPCM(pcm, sampleRate){\n"
    "          const bytesPerSample = 2; const blockAlign = 1*bytesPerSample; const byteRate = sampleRate*blockAlign;\n"
    "          const dataSize = pcm.length * bytesPerSample;\n"
    "          const buffer = new ArrayBuffer(44 + dataSize);\n"
    "          const view = new DataView(buffer);\n"
    "          function writeStr(o, s){ for(let i=0;i<s.length;i++) view.setUint8(o+i, s.charCodeAt(i)); }\n"
    "          let p=0; writeStr(p, 'RIFF'); p+=4; view.setUint32(p, 36+dataSize, true); p+=4; writeStr(p, 'WAVE'); p+=4; writeStr(p, 'fmt '); p+=4;\n"
    "          view.setUint32(p, 16, true); p+=4; view.setUint16(p, 1, true); p+=2; view.setUint16(p, 1, true); p+=2; view.setUint32(p, sampleRate, true); p+=4;\n"
    "          view.setUint32(p, byteRate, true); p+=4; view.setUint16(p, blockAlign, true); p+=2; view.setUint16(p, 16, true); p+=2; writeStr(p, 'data'); p+=4;\n"
    "          view.setUint32(p, dataSize, true); p+=4;\n"
    "          let o=p; for(let i=0;i<pcm.length;i++,o+=2){ view.setInt16(o, pcm[i], true); }\n"
    "          return new Blob([view], {type:'audio/wav'});\n"
    "        }\n"
    "        return wavFromPCM(pcm16, targetRate);\n"
    "      })(seconds);\n"
    "      setAnyStatus('上传识别中…');\n"
    "      const fd = new FormData(); fd.append('audio', wavBlob, 'audio.wav');\n"
    "      const resp = await fetch('/web/asr/transcribe', { method:'POST', body: fd });\n"
    "      const data = await resp.json().catch(()=>({success:false,message:'解析响应失败'}));\n"
    "      if (data.success && data.text){\n"
    "        if (targetInput){ if (targetInput.value && !targetInput.value.endsWith(' ')) targetInput.value += ' '; targetInput.value += data.text; }\n"
    "        setAnyStatus('转写成功'); return true;\n"
    "      } else { setAnyStatus('转写失败：' + (data.message || '未知错误')); return false; }\n"
    "    }catch(e){ setAnyStatus('服务器识别失败：' + e); return false; }\n"
    "    finally{ stopAudio(); stopMic(); }\n"
    "  }\n"
        "  function stopMic(){\n"
        "    try{ if(micStream){ micStream.getTracks().forEach(t=>t.stop()); } }catch(_){}\n"
        "    micStream = null;\n"
        "  }\n"
    "  function stopAudio(){\n"
    "    if (rafId){ cancelAnimationFrame(rafId); rafId = 0; }\n"
    "    try{ if(audioCtx){ audioCtx.close(); } }catch(_){}\n"
    "    audioCtx = null; analyser = null;\n"
    "    if (levelEl){ levelEl.value = 0; }\n"
    "    try{ if(waveCtx2d && waveCanvas){ waveCtx2d.clearRect(0,0,waveCanvas.width,waveCanvas.height); } }catch(_){}\n"
    "  }\n"
    "  async function startLevelMeter(stream){\n"
    "    try{\n"
    "      audioCtx = new (window.AudioContext || window.webkitAudioContext)();\n"
    "      if (audioCtx.state === 'suspended'){ try{ await audioCtx.resume(); }catch(_){} }\n"
    "      const source = audioCtx.createMediaStreamSource(stream);\n"
    "      analyser = audioCtx.createAnalyser();\n"
    "      analyser.fftSize = 2048;\n"
    "      // 保持音频图活跃：零增益连接到输出，避免某些实现不拉取数据\n"
    "      const zeroGain = audioCtx.createGain();\n"
    "      zeroGain.gain.value = 0;\n"
    "      source.connect(analyser);\n"
    "      source.connect(zeroGain);\n"
    "      zeroGain.connect(audioCtx.destination);\n"
    "      const data = new Uint8Array(analyser.fftSize);\n"
    "      const tick = ()=>{\n"
    "        if(!analyser) return;\n"
    "        analyser.getByteTimeDomainData(data);\n"
    "        let sum = 0;\n"
    "        for(let i=0;i<data.length;i++){ const v=(data[i]-128)/128; sum += v*v; }\n"
    "        const rms = Math.sqrt(sum/data.length);\n"
    "        const pct = Math.min(100, Math.max(0, Math.round(rms*100*2)));\n"
    "        if (levelEl){ levelEl.value = pct; }\n"
    "        if (waveCtx2d && waveCanvas){ const W=waveCanvas.width, H=waveCanvas.height; waveCtx2d.fillStyle='#fff'; waveCtx2d.fillRect(0,0,W,H); waveCtx2d.strokeStyle='#1677ff'; waveCtx2d.lineWidth=1; waveCtx2d.beginPath(); for(let x=0;x<W;x++){ const i=Math.floor(x*data.length/W); const v=(data[i]-128)/128; const y=H/2 - v*(H*0.45); if(x===0) waveCtx2d.moveTo(x,y); else waveCtx2d.lineTo(x,y); } waveCtx2d.stroke(); }\n"
    "        rafId = requestAnimationFrame(tick);\n"
    "      };\n"
    "      tick();\n"
    "    }catch(_){}\n"
    "  }\n"
    "  function buildConstraints(){\n"
    "    const audio = { echoCancellation: !!(chkEC && chkEC.checked), noiseSuppression: !!(chkNS && chkNS.checked), autoGainControl: !!(chkAGC && chkAGC.checked) };\n"
    "    if (deviceSel && deviceSel.value){ audio.deviceId = { exact: deviceSel.value }; }\n"
    "    // 可选的参考采样率/声道；部分设备会忽略\n"
    "    // audio.sampleRate = 48000; audio.channelCount = 1;\n"
    "    return { audio, video: false };\n"
    "  }\n"
    "  async function populateDevices(){\n"
    "    if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices || !deviceSel) return;\n"
    "    try{\n"
    "      const list = await navigator.mediaDevices.enumerateDevices();\n"
    "      const inputs = list.filter(d=>d.kind==='audioinput');\n"
    "      const selected = deviceSel.value || '';\n"
    "      deviceSel.innerHTML = '';\n"
    "      const def = document.createElement('option'); def.value=''; def.textContent='默认麦克风'; deviceSel.appendChild(def);\n"
    "      inputs.forEach(d=>{ const o=document.createElement('option'); o.value=d.deviceId; o.textContent=d.label||('麦克风 '+d.deviceId.slice(0,6)); deviceSel.appendChild(o); });\n"
    "      // 恢复选择\n"
    "      const ids = inputs.map(i=>i.deviceId); if (selected && ids.includes(selected)) deviceSel.value = selected;\n"
    "    }catch(_){}\n"
    "  }\n"
        "  function attachMic(form){\n"
        "    const input = form.querySelector('input[name=\"question\"]');\n"
        "    if(!input) return;\n"
        "    const status = document.createElement('span');\n"
        "    status.className = 'meta';\n"
        "    status.style.marginLeft = '6px';\n"
    "    // 音量条\n"
    "    levelEl = document.createElement('progress');\n"
    "    levelEl.max = 100;\n"
    "    levelEl.value = 0;\n"
    "    levelEl.style.width = '120px';\n"
    "    levelEl.style.marginLeft = '8px';\n"
    "    // 波形画布（按住说话时显示）\n"
    "    const waveCv = document.createElement('canvas'); waveCv.className='wave'; waveCv.width=240; waveCv.height=48; waveCv.style.marginLeft='8px'; waveCv.style.border='1px solid #eee'; waveCv.style.borderRadius='4px';\n"
    "    // 设备选择\n"
    "    deviceSel = document.createElement('select');\n"
    "    deviceSel.style.marginLeft = '6px';\n"
    "    deviceSel.title = '选择音频输入设备';\n"
    "    const opt = document.createElement('option'); opt.value=''; opt.textContent='默认麦克风'; deviceSel.appendChild(opt);\n"
    "    // 音频处理选项\n"
    "    chkEC = document.createElement('input'); chkEC.type='checkbox'; chkEC.checked = true;\n"
    "    chkNS = document.createElement('input'); chkNS.type='checkbox'; chkNS.checked = true;\n"
    "    chkAGC = document.createElement('input'); chkAGC.type='checkbox'; chkAGC.checked = false;\n"
    "    const lblEC = document.createElement('label'); lblEC.appendChild(chkEC); lblEC.appendChild(document.createTextNode(' 回声消除')); lblEC.style.marginLeft='6px';\n"
    "    const lblNS = document.createElement('label'); lblNS.appendChild(chkNS); lblNS.appendChild(document.createTextNode(' 降噪')); lblNS.style.marginLeft='6px';\n"
    "    const lblAGC = document.createElement('label'); lblAGC.appendChild(chkAGC); lblAGC.appendChild(document.createTextNode(' 自动增益')); lblAGC.style.marginLeft='6px';\n"
    "    // 自动回退服务器识别（安卓默认开启）\n"
    "    const isAndroidUA = /Android/i.test(navigator.userAgent);\n"
    "    let chkAutoFb = document.createElement('input'); chkAutoFb.type='checkbox'; chkAutoFb.checked = isAndroidUA;\n"
    "    const lblAutoFb = document.createElement('label'); lblAutoFb.appendChild(chkAutoFb); lblAutoFb.appendChild(document.createTextNode(' 失败自动用服务器识别')); lblAutoFb.style.marginLeft='6px';\n"
    "    // 设备信息\n"
    "    deviceEl = document.createElement('small');\n"
    "    deviceEl.className = 'meta';\n"
    "    deviceEl.style.marginLeft = '6px';\n"
    "    let btn = document.createElement('button');\n"
    "    btn.type = 'button';\n"
    "    btn.textContent = '🎤 按住说话';\n"
    "    btn.style.padding = '6px 10px';\n"
    "    btn.style.cursor = 'pointer';\n"
    "    btn.title = '按住开始录音，松开结束并识别';\n"
    "    let testBtn = document.createElement('button');\n"
    "    testBtn.type = 'button';\n"
    "    testBtn.textContent = '🧪 测试麦克风';\n"
    "    testBtn.style.padding = '6px 10px';\n"
    "    testBtn.style.cursor = 'pointer';\n"
    "    testBtn.addEventListener('click', async () => {\n"
    "      status.textContent = '测试模式：仅采集麦克风显示音量';\n"
    "      try{\n"
    "        if (activeRecog){ try{ activeRecog.stop(); }catch(_){} }\n"
    "        stopAudio(); stopMic();\n"
    "        const cons = buildConstraints();\n"
    "        micStream = await navigator.mediaDevices.getUserMedia(cons);\n"
    "        await startLevelMeter(micStream);\n"
    "        const at = micStream.getAudioTracks()[0];\n"
    "        const muted = at ? (at.muted || !at.enabled) : false;\n"
    "        const label = at && at.label ? at.label : '未知设备';\n"
    "        const sr = (audioCtx && audioCtx.sampleRate) ? audioCtx.sampleRate : '未知采样率';\n"
    "        deviceEl.textContent = `输入设备: ${label} · 采样率: ${sr}${muted ? ' ·(静音/禁用)' : ''}`;\n"
    "        // 2秒后如电平仍接近0，提示可能设备不对或被系统路由抑制\n"
    "        setTimeout(()=>{ if (levelEl && Number(levelEl.value) < 3){ status.textContent = '持续接近静音：请尝试切换设备下拉框、关闭蓝牙耳机或在系统音频设置切换输入源'; } }, 2000);\n"
    "        // 如已授予权限，刷新设备列表展示各输入源\n"
    "        populateDevices();\n"
    "        setTimeout(()=>{ stopAudio(); stopMic(); status.textContent = '测试结束'; }, 15000);\n"
    "      }catch(e){ status.textContent = '测试失败: ' + e; }\n"
    "    });\n"
    "    let serverBtn = document.createElement('button');\n"
    "    serverBtn.type = 'button';\n"
    "    serverBtn.textContent = '☁ 服务器识别';\n"
    "    serverBtn.style.padding = '6px 10px';\n"
    "    serverBtn.style.cursor = 'pointer';\n"
    "    serverBtn.addEventListener('click', async () => {\n"
    "      await serverTranscribe(getRecordSeconds(), input);\n"
    "    });\n"
    "    // 按住说话：按下开始，松开结束\n"
    "    function bindHoldPress(targetBtn, targetInput, hostEl){\n"
    "      const down = async ()=>{ try{ const cv = hostEl ? hostEl.querySelector('canvas.wave') : null; if (cv){ waveCanvas = cv; waveCtx2d = cv.getContext('2d'); } await startHoldRecord(targetInput); targetBtn.classList.add('recording'); targetBtn.textContent='🎤 录音中…松开结束'; status.textContent='按住录音中…'; }catch(e){ status.textContent='启动录音失败: '+e; } };\n"
    "      const up = async ()=>{ try{ const ok = await stopHoldRecord(targetInput); if (ok){ status.textContent='转写成功，点击发送按钮再发送'; } }finally{ targetBtn.classList.remove('recording'); targetBtn.textContent='🎤 按住说话'; } };\n"
    "      targetBtn.addEventListener('mousedown', down); targetBtn.addEventListener('mouseup', up); targetBtn.addEventListener('mouseleave', up);\n"
    "      targetBtn.addEventListener('touchstart', (e)=>{ e.preventDefault(); down(); }, {passive:false});\n"
    "      targetBtn.addEventListener('touchend', (e)=>{ e.preventDefault(); up(); }, {passive:false});\n"
    "      targetBtn.addEventListener('pointerdown', down); targetBtn.addEventListener('pointerup', up);\n"
    "    }\n"
    "    bindHoldPress(btn, input, form);\n"
    "    // 取消点击一次性语音识别，改为按住说话\n"
        "    form.appendChild(btn);\n"
    "    form.appendChild(testBtn);\n"
    "    form.appendChild(serverBtn);\n"
    "    form.appendChild(deviceSel);\n"
    "    form.appendChild(lblEC);\n"
    "    form.appendChild(lblNS);\n"
    "    form.appendChild(lblAGC);\n"
    "    form.appendChild(lblAutoFb);\n"
    "    form.appendChild(status);\n"
    "    form.appendChild(levelEl);\n"
    "    form.appendChild(waveCv);\n"
    "    form.appendChild(deviceEl);\n"
        "    if(!hasSR){ status.textContent = '浏览器不支持语音识别'; } else if(!secureOK){ status.textContent = '非安全环境（需 HTTPS 或 localhost）'; }\n"
        "  }\n"
        "  document.querySelectorAll('form[action=\"/web/vision/analyze\"]').forEach(attachMic);\n"
        "  // 简易连续对话（视觉分析页专用）\n"
        "  const chatBox = document.getElementById('chat-box');\n"
    "  if (chatBox){\n"
        "    const chatMsgs = document.getElementById('chat-messages');\n"
        "    const chatInput = document.getElementById('chat-input');\n"
        "    const chatSend = document.getElementById('chat-send');\n"
    "    const chatImages = document.getElementById('chat-images');\n"
        "    const chatDate = document.getElementById('chat-date');\n"
    "    const chatClear = document.getElementById('chat-clear');\n"
        "    const chatStatus = document.getElementById('chat-status');\n"
    "    const chatVoice = document.getElementById('chat-voice');\n"
    "    const chatSourceEl = document.getElementById('chat-source');\n"
    "    const chatStu = document.getElementById('chat-student-id');\n"
    "    // 会话ID（持久化到 localStorage，按来源区分）\n"
    "    let chatConvId = null;\n"
    "    try{ const k = 'xiaozhi_conv_id_' + (chatSourceEl?chatSourceEl.value:'vision'); chatConvId = localStorage.getItem(k) || null; }catch(_){}\n"
        "    let history = [];\n"
    "    // 记忆学号\n"
    "    try{ const savedSid = localStorage.getItem('xiaozhi_student_id'); if (chatStu && savedSid) chatStu.value = savedSid; }catch(_){}\n"
        "    function addMsg(role, content){\n"
        "      const wrap = document.createElement('div'); wrap.className = 'chat-item ' + role;\n"
        "      const who = document.createElement('div'); who.className = 'chat-role'; who.textContent = role==='user'?'你':'助手';\n"
        "      const text = document.createElement('div'); text.className = 'chat-content'; text.textContent = content;\n"
        "      wrap.appendChild(who); wrap.appendChild(text); chatMsgs.appendChild(wrap); chatMsgs.scrollTop = chatMsgs.scrollHeight;\n"
        "    }\n"
        "    function setStatus(t){ if(chatStatus) chatStatus.textContent = t||''; }\n"
    "    chatClear.addEventListener('click', ()=>{ history = []; chatMsgs.innerHTML=''; setStatus(''); try{ const k='xiaozhi_conv_id_' + (chatSourceEl?chatSourceEl.value:'vision'); localStorage.removeItem(k); }catch(_){} chatConvId=null; });\n"
        "    async function send(){\n"
    "      const q = (chatInput.value||'').trim(); if(!q) return;\n"
        "      addMsg('user', q); chatInput.value=''; setStatus('思考中…'); chatSend.disabled = true;\n"
        "      try{\n"
    "        const files = [];\n"
    "        if (chatImages){ for (const opt of Array.from(chatImages.selectedOptions)){ if(opt.value) files.push(opt.value); } }\n"
    "        const sid = (chatStu && chatStu.value)?chatStu.value.trim():''; if (sid){ try{ localStorage.setItem('xiaozhi_student_id', sid); }catch(_){} }\n"
    "        // 生成或读取会话ID\n"
    "        if (!chatConvId){ chatConvId = (Date.now().toString(36) + Math.random().toString(36).slice(2,8)); try{ const k='xiaozhi_conv_id_' + (chatSourceEl?chatSourceEl.value:'vision'); localStorage.setItem(k, chatConvId); }catch(_){} }\n"
    "        const payload = { question: q, history: history, date: (chatDate?chatDate.value:''), files: files, source: (chatSourceEl?chatSourceEl.value:'vision'), max_images: getMaxImages(), student_id: sid, conversation_id: chatConvId };\n"
        "        const resp = await fetch('/web/vision/chat', { method:'POST', headers: { 'Content-Type':'application/json' }, body: JSON.stringify(payload) });\n"
        "        const data = await resp.json().catch(()=>({success:false,message:'解析响应失败'}));\n"
        "        if (data.success){\n"
    "          const reply = data.reply || ''; addMsg('assistant', reply);\n"
    "          // 同步可能由服务器生成的新会话ID\n"
    "          if (data.conversation_id && (!chatConvId || data.conversation_id !== chatConvId)){ chatConvId = data.conversation_id; try{ const k='xiaozhi_conv_id_' + (chatSourceEl?chatSourceEl.value:'vision'); localStorage.setItem(k, chatConvId); }catch(_){} }\n"
        "          // 维护简易历史（仅文本），长度控制在最近8轮\n"
        "          history.push({role:'user', content:q}); history.push({role:'assistant', content:reply});\n"
        "          if (history.length > 16) history = history.slice(-16);\n"
        "          setStatus('');\n"
        "        }else{ setStatus('失败：' + (data.message||'未知错误')); }\n"
        "      }catch(e){ setStatus('异常：' + e); } finally { chatSend.disabled = false; }\n"
        "    }\n"
        "    chatSend.addEventListener('click', send);\n"
        "    chatInput.addEventListener('keydown', (e)=>{ if(e.key==='Enter' && !e.shiftKey){ e.preventDefault(); send(); } });\n"
    "    if (chatVoice){\n"
    "      // 聊天区独立波形画布\n"
    "      const chatWave = document.createElement('canvas'); chatWave.className='wave'; chatWave.width=260; chatWave.height=48; chatWave.style.marginLeft='8px'; chatWave.style.border='1px solid #eee'; chatWave.style.borderRadius='4px';\n"
    "      try{ chatVoice.parentNode.insertBefore(chatWave, chatSend); }catch(_){}\n"
    "      const down = async ()=>{ try{ waveCanvas = chatWave; waveCtx2d = chatWave.getContext('2d'); await startHoldRecord(chatInput); chatVoice.classList.add('recording'); chatVoice.textContent='🎤 录音中…松开结束'; setStatus('按住录音中…'); }catch(e){ setStatus('启动录音失败: '+e); } };\n"
    "      const up = async ()=>{ const ok = await stopHoldRecord(chatInput); chatVoice.classList.remove('recording'); chatVoice.textContent='🎤 语音输入'; if (ok) setStatus('转写成功，点击“发送”按钮发送'); };\n"
    "      chatVoice.addEventListener('mousedown', down); chatVoice.addEventListener('mouseup', up); chatVoice.addEventListener('mouseleave', up);\n"
    "      chatVoice.addEventListener('touchstart', (e)=>{ e.preventDefault(); down(); }, {passive:false});\n"
    "      chatVoice.addEventListener('touchend', (e)=>{ e.preventDefault(); up(); }, {passive:false});\n"
    "      chatVoice.addEventListener('pointerdown', down); chatVoice.addEventListener('pointerup', up);\n"
    "    }\n"
        "  }\n"
        "  // 结束聊天逻辑\n"
        "  // 若已授权，预先列出设备\n"
        "  if (navigator.permissions && navigator.permissions.query){\n"
        "    navigator.permissions.query({name:'microphone'}).then(p=>{ if (p.state==='granted'){ populateDevices(); } });\n"
        "  }\n"
        "})();\n"
        "</script>\n"
    )
    tail = "</body>\n</html>\n"
    html = head + body + script + tail
    return web.Response(text=html, content_type="text/html", charset="utf-8")


def _safe_join(base: str, *paths: str) -> str:
    path = os.path.abspath(os.path.join(base, *paths))
    if not path.startswith(os.path.abspath(base) + os.sep):
        raise web.HTTPBadRequest(text="非法路径")
    return path


class WebUI:
    def __init__(self, config: dict):
        self.config = config
        self.logger = setup_logging()
        # 工作目录下 data 作为静态根
        self.data_root = os.path.abspath(os.path.join(os.getcwd(), "data"))

    def _append_conversation_event(self, conversation_id: str, source: str, student_id: str, question: str, reply: str, files: list):
        """将一次对话轮次追加到 data/conversations/YYYYMMDD/<conversation_id>.jsonl
        采用 JSONL，每行结构：{"timestamp","source","student_id","question","reply","files"}
        """
        try:
            from datetime import datetime as _dt
            import json as _json
            # 存档前净化文本，去除 Markdown/LaTeX/特殊符号
            try:
                from core.utils import textUtils as _txu
                _q = _txu.sanitize_for_device(question or "")
                _r = _txu.sanitize_for_device(reply or "")
            except Exception:
                _q = question or ""
                _r = reply or ""
            now = _dt.now()
            date_str = now.strftime("%Y%m%d")
            out_dir = os.path.join(self.data_root, "conversations", date_str)
            os.makedirs(out_dir, exist_ok=True)
            if not conversation_id:
                # 兜底生成一个
                conversation_id = now.strftime("%H%M%S")
            line = {
                "timestamp": now.isoformat(timespec="seconds"),
                "source": (source or "vision"),
                "student_id": (student_id or ""),
                "question": _q,
                "reply": _r,
                "files": [f for f in (files or []) if f],
            }
            with open(os.path.join(out_dir, f"{conversation_id}.jsonl"), "a", encoding="utf-8") as f:
                f.write(_json.dumps(line, ensure_ascii=False) + "\n")
            return date_str
        except Exception as e:
            try:
                self.logger.warning(f"保存对话记录失败: {e}")
            except Exception:
                pass
            return None

    def _save_analysis_event(self, source: str, student_id: str, question: str, reply: str, files: list):
        """将一次分析记录保存到 data/analyses/YYYYMMDD/ 下。
        文件名: HHMMSS_source.json，同时追加到 index.jsonl 便于聚合。
        """
        try:
            from datetime import datetime as _dt
            import json as _json
            from io import BytesIO
            # 归档前净化文本，保持展示一致性
            try:
                from core.utils import textUtils as _txu
                _q = _txu.sanitize_for_device(question or "")
                _r = _txu.sanitize_for_device(reply or "")
            except Exception:
                _q = question or ""
                _r = reply or ""
            now = _dt.now()
            date_str = now.strftime("%Y%m%d")
            time_str = now.strftime("%H%M%S")
            out_dir = os.path.join(self.data_root, "analyses", date_str)
            os.makedirs(out_dir, exist_ok=True)
            thumbs_rel = []
            # 可选缩略图生成（需要 Pillow）
            try:
                from PIL import Image as _Image
                thumbs_dir = os.path.join(out_dir, "thumbs")
                os.makedirs(thumbs_dir, exist_ok=True)
                base_dir = os.path.join(self.data_root, "generated_images" if (source or "") == "generated" else "vision_records")
                idx = 0
                for ref in (files or [])[:8]:  # 缩略图最多生成8张
                    try:
                        ref = (ref or "").replace("\\", "/")
                        if "/" not in ref:
                            continue
                        d, fn = ref.split("/", 1)
                        in_path = _safe_join(base_dir, d, fn)
                        if not os.path.isfile(in_path):
                            continue
                        with _Image.open(in_path) as im:
                            im = im.convert("RGB")
                            im.thumbnail((240, 240))
                            out_name = f"{time_str}_{idx}.jpg"
                            out_path = os.path.join(thumbs_dir, out_name)
                            im.save(out_path, format="JPEG", quality=78, optimize=True)
                            thumbs_rel.append(f"analyses/{date_str}/thumbs/{out_name}")
                            idx += 1
                    except Exception:
                        continue
            except Exception:
                # 未安装 Pillow 或生成失败，忽略
                pass
            event = {
                "timestamp": now.isoformat(timespec="seconds"),
                "date": date_str,
                "time": time_str,
                "source": (source or ""),
                "student_id": (student_id or ""),
                "question": _q,
                "reply": _r,
                "files": files or [],
                "thumbs": thumbs_rel,
            }
            with open(os.path.join(out_dir, f"{time_str}_{source or 'unknown'}.json"), "w", encoding="utf-8") as f:
                _json.dump(event, f, ensure_ascii=False, indent=2)
            # 追加到每日索引
            try:
                with open(os.path.join(out_dir, "index.jsonl"), "a", encoding="utf-8") as lf:
                    lf.write(_json.dumps(event, ensure_ascii=False) + "\n")
            except Exception:
                pass
        except Exception as e:
            try:
                self.logger.warning(f"保存分析记录失败: {e}")
            except Exception:
                pass

    async def index(self, request: web.Request) -> web.Response:
        body = (
            "<div class=\"hero\">\n"
            "    <h1>数据分析中心</h1>\n"
            "    <p>查看视觉记录、管理生成图片，并对内容进行多图联机分析，帮助掌握全面数据动态。</p>\n"
            "    <div class=\"actions\">\n"
            "        <a class=\"btn btn-primary\" href=\"/web/vision\">✨ 视觉大屏分析</a>\n"
            "        <a class=\"btn btn-primary\" style=\"background:#52c41a; border-color:#52c41a; box-shadow:0 2px 4px rgba(82,196,26,.15);\" href=\"/web/vision/present\" target=\"_blank\">🖥️ 开启大屏演示</a>\n"
            "        <a class=\"btn btn-outline\" href=\"/web/generated\">🖼️ 生成图片库</a>\n"
            "        <a class=\"btn btn-outline\" href=\"/web/generated/analyze\">🧠 智能跨图分析</a>\n"
            "    </div>\n"
            "    <div class=\"meta\" style=\"margin-top:12px; opacity:0.8;\">💡 提示：在“生成图片”页可选择学号并点击“应用学号”进行筛选拦截。&nbsp;&nbsp;|<span style=\"margin-left:8px;\">🩺 <a href=\"/xiaozhi/status/\" target=\"_blank\" style=\"color:#5c6a79; text-decoration:underline;\">系统接口体检报告</a></span></div>\n"
            "</div>\n"
            "\n"
            "<h3 class=\"section-header\">🛠️ 服务与治理功能</h3>\n"
            "<div class=\"grid home-quick\">\n"
            "    <div class=\"card\">\n"
            "        <h3>📷 视觉记录管理</h3>\n"
            "        <p>浏览所有客户端实时抓拍与感知数据；支持基于时间戳与学号维度的定向筛查，自带AI会话分析支持。</p>\n"
            "        <div class=\"actions\"><a class=\"btn btn-primary\" style=\"width:100%; box-sizing:border-box;\" href=\"/web/vision\">进入视界中心</a></div>\n"
            "    </div>\n"
            "    <div class=\"card\">\n"
            "        <h3>🗂️ 图片生成归档</h3>\n"
            "        <p>中心下发至远端设备的全部渲染历史沉淀库；支撑按需查阅、清理并能直接进入学号数据专向隔离分析。</p>\n"
            "        <div class=\"actions\"><a class=\"btn btn-primary\" style=\"width:100%; box-sizing:border-box;\" href=\"/web/generated\">浏览历史生成</a></div>\n"
            "    </div>\n"
            "    <div class=\"card\">\n"
            "        <h3>🧠 分布式多模态推理</h3>\n"
            "        <p>汇聚已存储的多张素材图片，向大语言模型连续发问并执行深层次跨图知识关联抽取。</p>\n"
            "        <div class=\"actions\"><a class=\"btn btn-primary\" style=\"width:100%; box-sizing:border-box;\" href=\"/web/generated/analyze\">唤起推理控制台</a></div>\n"
            "    </div>\n"
            "    <div class=\"card\">\n"
            "        <h3>💬 全局对话追溯</h3>\n"
            "        <p>跟踪系统内发生的所有对话过程明细，审计并检索特定知识节点或异常语料，并附带关联信息。</p>\n"
            "        <div class=\"actions\"><a class=\"btn btn-primary\" style=\"width:100%; box-sizing:border-box;\" href=\"/web/conversations\">查阅所有对话</a></div>\n"
            "    </div>\n"
            "</div>\n"
        )
        return _html_page("智慧课堂管理后台", body)

    async def upload_form(self, request: web.Request) -> web.Response:
        body = (
            "<div class=\"card\">\n"
            "  <div class=\"meta\">通过网页上传图片并进行视觉分析（支持 JPG/PNG/GIF/WebP/TIFF/BMP，最大20MB）</div>\n"
            "  <form method=\"post\" action=\"/web/vision/upload\" enctype=\"multipart/form-data\" style=\"display:flex; gap:8px; flex-wrap:wrap; align-items:center;\">\n"
            "    <input type=\"file\" name=\"image\" accept=\"image/*\" required />\n"
            "    <input type=\"text\" name=\"question\" placeholder=\"输入问题，例如：请用一句话描述图片\" style=\"flex:1 1 360px; padding:6px 8px;\" required />\n"
            "    <input type=\"text\" name=\"student_id\" placeholder=\"学号（必填）\" style=\"width:160px;\" required />\n"
            "    <button type=\"submit\" class=\"btn btn-primary\">开始分析</button>\n"
            "  </form>\n"
            "  <div class=\"meta\">提示：分析结果与上传图片会保存到 data/vision_records/ 按日期分目录，便于后续在“视觉记录”中查看与再次分析。</div>\n"
            "</div>\n"
        )
        return _html_page("上传图片分析", body)

    async def upload_analyze(self, request: web.Request) -> web.Response:
        data = await request.post()
        question = (data.get("question") or "").strip()
        student_id = (data.get("student_id") or "").strip()
        file_field = data.get("image")
        if not question:
            raise web.HTTPBadRequest(text="缺少问题")
        if not student_id:
            raise web.HTTPBadRequest(text="缺少学号")
        if not file_field:
            raise web.HTTPBadRequest(text="未选择图片文件")
        # 读取文件字节
        try:
            filename = getattr(file_field, "filename", "uploaded") or "uploaded"
            ct = getattr(file_field, "content_type", "application/octet-stream") or "application/octet-stream"
            fobj = getattr(file_field, "file", None)
            if fobj is None:
                raise ValueError("无法读取文件内容")
            img_bytes = fobj.read()
            if not img_bytes:
                raise ValueError("图片为空")
        except Exception as e:
            raise web.HTTPBadRequest(text=f"读取图片失败: {e}")

        # 规范化到JPEG（若可能），提升视觉模型兼容性
        out_bytes = img_bytes
        out_ext = ".jpg"
        try:
            from PIL import Image, ImageFile  # type: ignore
            from io import BytesIO
            ImageFile.LOAD_TRUNCATED_IMAGES = True
            with BytesIO(img_bytes) as bio:
                im = Image.open(bio)
                try:
                    im.load()
                except Exception:
                    pass
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            buf = BytesIO()
            try:
                im.save(buf, format="JPEG", quality=85, optimize=True)
                out_bytes = buf.getvalue()
                out_ext = ".jpg"
            except Exception:
                buf.seek(0); buf.truncate(0)
                im.save(buf, format="PNG", optimize=True)
                out_bytes = buf.getvalue()
                out_ext = ".png"
            finally:
                try: buf.close()
                except Exception: pass
        except Exception:
            # 无 Pillow 或重编码失败：按原始扩展名保留
            try:
                lower = filename.lower()
                if lower.endswith((".png",".gif",".bmp",".webp",".tiff",".tif",".jpeg",".jpg")):
                    out_ext = "." + lower.rsplit(".",1)[-1]
            except Exception:
                out_ext = ".jpg"

        # 序列化为base64传入 VLLMProvider
        import base64 as _b64
        img_b64 = _b64.b64encode(out_bytes).decode("utf-8")

        # 构建 VLLM 实例
        current_config = self.config
        sel = current_config.get("selected_module", {}).get("VLLM")
        if not sel:
            raise web.HTTPBadRequest(text="未配置默认视觉模块")
        vllm_type = sel if "type" not in current_config["VLLM"][sel] else current_config["VLLM"][sel]["type"]
        vllm = create_instance(vllm_type, current_config["VLLM"][sel])

        # 附加学号到问题（与其他页面保持一致）
        user_prompt = question + (f"（学号：{student_id}）" if student_id else "") + "(请使用中文回复)"
        result_text = vllm.response(user_prompt, img_b64)
        # 存档/展示前净化文本
        try:
            from core.utils import textUtils as _txu
            _result_clean = _txu.sanitize_for_device(result_text or "")
        except Exception:
            _result_clean = result_text

        # 落盘到 data/vision_records/YYYYMMDD
        from datetime import datetime as _dt
        day = _dt.now().strftime("%Y%m%d")
        ts = _dt.now().strftime("%H%M%S")
        out_dir = os.path.join(self.data_root, "vision_records", day)
        os.makedirs(out_dir, exist_ok=True)
        base_name = f"{ts}_webupload"
        img_name = base_name + out_ext
        json_name = base_name + ".json"
        img_path = os.path.join(out_dir, img_name)
        json_path = os.path.join(out_dir, json_name)
        try:
            with open(img_path, "wb") as f:
                f.write(out_bytes)
            # 保存与 VisionHandler 结构相近的 JSON
            import json as _json
            meta = {
                "success": True,
                "action": "RESPONSE",
                "response": _result_clean,
            }
            # 学号必填，始终写入
            meta["student_id"] = student_id
            with open(json_path, "w", encoding="utf-8") as jf:
                _json.dump(meta, jf, ensure_ascii=False, indent=2)
        except Exception as e:
            # 保存失败不影响返回，但给出提示
            try:
                self.logger.warning(f"保存上传记录失败: {e}")
            except Exception:
                pass

        # 记录到分析历史（来源 vision，单图）
        try:
            self._save_analysis_event(
                source="vision",
                student_id=student_id,
                question=question,
                reply=result_text,
                files=[f"{day}/{img_name}"]
            )
        except Exception:
            pass

        body = f"""
<p>图片已保存：{img_name}（{day}）</p>
<img class=\"thumb\" src=\"/static/vision_records/{day}/{img_name}\" alt=\"img\" />
<h3>问题</h3>
<div class=\"json\">{question}{('（学号：'+student_id+'）') if student_id else ''}</div>
<h3>结果</h3>
<div class=\"json\">{_result_clean}</div>
<p><a href=\"/web/vision?date={day}\">返回视觉记录</a> · <a href=\"/web/vision/upload\">继续上传</a></p>
"""
        return _html_page("上传图片分析结果", body)

    async def vision_list(self, request: web.Request) -> web.Response:
        return await self._render_vision_page(request, is_present=False)

    async def vision_present(self, request: web.Request) -> web.Response:
        """纯净展示模式，仅展示选中的视觉记录"""
        return await self._render_vision_page(request, is_present=True)

    async def _render_vision_page(self, request: web.Request, is_present: bool = False) -> web.Response:
        # 支持日期与学号多选（GET 参数）：date=YYYYMMDD 或 dates=...（可多值/逗号分隔），sids=...
        today = datetime.now().strftime("%Y%m%d")
        def _collect_multi(query, key):
            vals = []
            try:
                arr = query.getall(key)  # 多值
            except Exception:
                arr = []
            if arr:
                for v in arr:
                    for p in (v or "").split(","):
                        p = p.strip()
                        if p:
                            vals.append(p)
            else:
                one = query.get(key) or ""
                if one:
                    for p in one.split(","):
                        p = p.strip()
                        if p:
                            vals.append(p)
            return vals

        selected_dates = _collect_multi(request.query, "dates") or ([request.query.get("date").strip()] if (request.query.get("date")) else [today])
        selected_classes = _collect_multi(request.query, "classes")
        selected_sids = _collect_multi(request.query, "sids")
        sid_keyword = request.query.get("sid_keyword", "").strip()
        filter_class_time = request.query.get("class_time") == "1"
        now_ts = time.time()
        
        recent_dates = [(datetime.now() - timedelta(days=i)).strftime("%Y%m%d") for i in range(0, 30)]

        # 聚合条目（当前筛选范围）
        items = []
        # 学号候选（扫描最近30天全部记录，便于下拉列表完整）
        all_sids = set()
        
        allowed_paths = None
        ordered_items_list = []
        
        # 无论是否 is_present，都读取大屏显示的状态，以便复原勾选框
        state_file = _safe_join(self.data_root, "vision_records", "present_state.json")
        if os.path.exists(state_file):
            import json as _json
            try:
                with open(state_file, "r", encoding="utf-8") as f:
                    jdata = _json.load(f)
                    ordered_items_list = jdata.get("items", [])
                    allowed_paths = set(ordered_items_list)
            except Exception:
                pass
        if allowed_paths is None:
            allowed_paths = set()

        for d in selected_dates:
            vdir = _safe_join(self.data_root, "vision_records", d)
            if not os.path.isdir(vdir):
                continue
            for name in sorted(os.listdir(vdir)):
                if name.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff")):
                    img_real_path = os.path.join(vdir, name)
                    if filter_class_time:
                        try:
                            if abs(now_ts - os.path.getmtime(img_real_path)) > 1800:
                                continue
                        except Exception:
                            pass
                    
                    if is_present and f"{d}/{name}" not in allowed_paths:
                        continue
                    base = name.rsplit(".", 1)[0]
                    json_path = os.path.join(vdir, base + ".json")
                    sid = None
                    try:
                        if os.path.isfile(json_path):
                            import json as _json
                            with open(json_path, "r", encoding="utf-8") as jf:
                                data = _json.load(jf)
                            if isinstance(data, dict):
                                sid = (data.get("student_id") or "").strip()
                    except Exception:
                        sid = None
                    items.append({
                        "date": d,
                        "img": f"/static/vision_records/{d}/{name}",
                        "json": f"/static/vision_records/{d}/{base}.json",
                        "file": name,
                        "sid": sid,
                    })

        # 补充学号候选：扫描所选日期下的所有 JSON 文件，只显示所选日期有记录的学号
        try:
            for d in selected_dates:
                vdir = _safe_join(self.data_root, "vision_records", d)
                if not os.path.isdir(vdir):
                    continue
                for name in os.listdir(vdir):
                    if not name.lower().endswith(".json"):
                        continue
                    
                    if filter_class_time:
                        try:
                            if abs(now_ts - os.path.getmtime(os.path.join(vdir, name))) > 1800:
                                continue
                        except Exception:
                            pass
                            
                    try:
                        import json as _json
                        with open(os.path.join(vdir, name), "r", encoding="utf-8") as jf:
                            data = _json.load(jf)
                        if isinstance(data, dict):
                            sid = (data.get("student_id") or "").strip()
                            if sid:
                                all_sids.add(sid)
                    except Exception:
                        continue
        except Exception:
            pass

        all_classes = set()
        all_student_suffixes = set()
        for s in all_sids:
            if s and len(s) >= 2 and s[:2].isdigit():
                all_classes.add(s[:2])
            if s and len(s) > 2:
                all_student_suffixes.add(s[2:])
            else:
                all_student_suffixes.add(s)

        if selected_classes:
            items = [it for it in items if any((it.get("sid") or "").startswith(c) for c in selected_classes)]

        if selected_sids:
            items = [it for it in items if any((it.get("sid") or "") == s or (it.get("sid") or "").endswith(s) for s in selected_sids)]

        if sid_keyword:
            items = [it for it in items if sid_keyword in (it.get("sid") or "")]

        cards = []
        sel_options = ["<option value=''>不使用图片</option>"]
        for it in reversed(items[-200:]):
            sel_options.append(f"<option value='{it['date']}/{it['file']}'>{it['date']} · {it['file']}</option>")

        date_opts_html = []
        for d in recent_dates:
            sel = " selected" if d in selected_dates else ""
            date_opts_html.append(f"<option value='{d}'{sel}>{d}</option>")
        # 不再合并所有本地已知学号，只显示当前所选日期下的班级和学号
        # try:
        #     for s in _list_known_sids():
        #         if s:
        #             all_sids.add(s)
        #             if len(s) >= 2 and s[:2].isdigit():
        #                 all_classes.add(s[:2])
        # except Exception:
        #     pass
            
        class_opts_html = []
        for c in sorted(all_classes):
            sel = " selected" if c in selected_classes else ""
            class_opts_html.append(f"<option value='{c}'{sel}>{c}</option>")
            
        sid_opts_html = []
        for s in sorted(all_student_suffixes):
            sel = " selected" if s in selected_sids else ""
            sid_opts_html.append(f"<option value='{s}'{sel}>{s}</option>")
        sid_fallback_html = "" if sid_opts_html else "<input name=\"sids\" type=\"text\" placeholder=\"手动输入后2位或完整学号\" style=\"width:180px;\" />"

        class_time_checked = "checked" if filter_class_time else ""
        selected_dates_str = ",".join(selected_dates)
        selected_classes_str = ",".join(selected_classes)
        selected_sids_str = ",".join(selected_sids)
        form_action = "/web/vision/present" if is_present else "/web/vision"

        chat_html = """
<section id="chat-box" class="card">
    <div class="meta">连续对话（可多选图片参与理解，按 Ctrl/Shift 多选）</div>
    <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin:6px 0;">
        <form id="filter-form" method="get" action="{form_action}" style="display:flex; gap:12px; align-items:center; flex-wrap:wrap;">
            <label class="meta">
                <input type="checkbox" name="class_time" value="1" {class_time_checked} style="transform: scale(1.2); margin-right: 4px;" /> 当堂课时(即时前后半小时)
            </label>
            <label class="meta">日期(多选):
                <select name="dates" id="filter-dates" multiple size="5">{date_opts}</select>
            </label>
            <label class="meta">班级(前2位):
                <select name="classes" id="filter-classes" multiple size="5">{class_opts}</select>
            </label>
            <label class="meta">学号(多选):
                <select name="sids" id="filter-sids" multiple size="5">{sid_opts}</select>
            </label>
            <label class="meta">或者搜索学号关键字:
                <input type="text" name="sid_keyword" value="{sid_keyword}" placeholder="例如: 03或0301" style="width:130px;" />
            </label>
            {sid_fallback}
            <button type="submit">应用筛选</button>
        </form>
        <input id="chat-dates" type="hidden" value="{selected_dates_str}" />
        <label class="meta">图片: <select id="chat-images" multiple size="6">{options}</select></label>
        <label class="meta">学号: <input id="chat-student-id" type="text" placeholder="可选(逗号分隔)" style="width:160px;" value="{selected_sids_str}" /></label>
        <button id="chat-clear" type="button">清空对话</button>
        <span id="chat-status" class="meta"></span>
        <input id="chat-source" type="hidden" value="vision" />
        <label class="meta">录音秒数: <input id="chat-record-seconds" type="number" min="1" max="30" value="3" style="width:64px;" /></label>
        <label class="meta">多图上限: <input id="chat-max-images" type="number" min="1" max="50" value="6" style="width:64px;" /></label>
    </div>
    <div id="chat-messages" style="max-height:300px; overflow:auto; background:#fafafa; padding:8px; border-radius:6px; border:1px solid #eee;"></div>
    <div style="display:flex; gap:8px; align-items:center; margin-top:8px;">
        <input id="chat-input" type="text" placeholder="输入你的问题，回车发送" style="flex:1 1 auto; padding:6px 8px;" />
        <button id="chat-voice" type="button">🎤 语音输入</button>
        <button id="chat-send" type="button">发送</button>
    </div>
    <style>
        .chat-item{{ display:flex; gap:8px; padding:6px 4px; }}
        .chat-item .chat-role{{ width:48px; color:#888; font-size:12px; flex:0 0 auto; }}
        .chat-item .chat-content{{ white-space:pre-wrap; }}
    </style>
</section>
""".format(
            date_opts=''.join(date_opts_html),
            class_opts=''.join(class_opts_html),
            sid_opts=''.join(sid_opts_html),
            options=''.join(sel_options),
            selected_dates_str=selected_dates_str,
            selected_sids_str=selected_sids_str,
            sid_keyword=sid_keyword,
            sid_fallback=sid_fallback_html,
            class_time_checked=class_time_checked,
            form_action=form_action,
        )

        # 学号候选 datalist（供再次分析表单使用）
        sid_datalist_html = "" if not all_sids else ("<datalist id=\"sid-list\">" + "".join([f"<option value='{s}'></option>" for s in sorted(all_sids)]) + "</datalist>")

        if not items:
            cards.append(f"<p>暂无记录（日期：{', '.join(selected_dates)}）。</p>")
        else:
            display_items = list(reversed(items))
            if is_present and ordered_items_list:
                item_dict = {f"{it['date']}/{it['file']}": it for it in display_items}
                display_items = [item_dict[p] for p in ordered_items_list if p in item_dict]
                
            for it in display_items:
                card_extra = ""
                draggable_attr = ""
                
                if is_present:
                    draggable_attr = 'draggable="true"'
                    card_extra = f"""<input type="hidden" class="card-path-data" value="{it['date']}/{it['file']}" />"""
                else:
                    checked_attr = 'checked' if f"{it['date']}/{it['file']}" in allowed_paths else ''
                    card_extra = f"""
    <div style="margin-bottom: 6px;">
      <label style="cursor: pointer; font-weight: bold; background: #e6f7ff; padding: 4px 8px; border-radius: 4px; display: inline-block;">
        <input type="checkbox" class="card-selector" {checked_attr} style="transform: scale(1.2); margin-right: 6px;" /> 选择展示此记录
      </label>
      <input type="hidden" name="date" value="{it['date']}" />
      <input type="hidden" name="file" value="{it['file']}" />
    </div>"""
                
                cards.append(
                    f"""
<div class="card" {draggable_attr} style="position: relative;">
{card_extra}
  <img class="thumb" src="{it['img']}" alt="img" />
  <div class="meta">日期: {it['date']} · 文件: {it['file']}{(' · 学号: '+it['sid']) if it.get('sid') else ''}</div>
  <details>
    <summary>查看分析 JSON</summary>
    <div class="json"><a href="{it['json']}" target="_blank">在新窗口打开</a></div>
  </details>
  <form method="post" action="/web/vision/analyze">
    <input type="hidden" name="date" value="{it['date']}" />
    <input type="hidden" name="file" value="{it['file']}" />
    <input type="text" name="question" placeholder="输入问题，例如：请用一句话描述图片" />
        <label class="meta">学号: <input name="student_id" type="text" placeholder="可选" list="sid-list" style="width:160px;" /></label>
    <button type="submit">再次分析</button>
  </form>
    <form method="post" action="/web/vision/delete" onsubmit="return confirm('确认删除该记录（图片及JSON）？');" style="margin-top:6px;">
        <input type="hidden" name="date" value="{it['date']}" />
        <input type="hidden" name="file" value="{it['file']}" />
        <button type="submit" style="background:#ff4d4f;color:#fff;border-color:#ff4d4f;" class="btn">删除</button>
    </form>
</div>
"""
                )

        filter_toggle_html = ""
        if not is_present:
            filter_toggle_html = """
<div style="margin: 10px 0; padding: 10px; background: #fff; border: 1px solid #ddd; border-radius: 6px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); display: flex; gap: 15px; align-items: center; flex-wrap: wrap;">
  <label style="font-weight: bold; cursor: pointer; font-size: 15px; color: #d9363e;">
    <input type="checkbox" id="toggle-selected-only" style="transform: scale(1.3); margin-right: 8px;" /> 仅展示选中的结果 (当前页)
  </label>
  <a href="/web/vision/present" target="_blank" class="btn btn-primary" style="padding: 4px 12px; border-radius: 4px; text-decoration: none;">打开大屏展示页</a>
  <span id="sync-status" style="color: #888; font-size: 13px;"></span>
</div>
<script>
document.addEventListener('DOMContentLoaded', () => {
    const toggle = document.getElementById('toggle-selected-only');
    const cards = document.querySelectorAll('.grid .card');
    const syncStatus = document.getElementById('sync-status');
    
    function updateVisibility() {
        const onlySelected = toggle.checked;
        cards.forEach(card => {
            const cb = card.querySelector('.card-selector');
            if (!cb) return;
            if (onlySelected && !cb.checked) {
                card.style.display = 'none';
            } else {
                card.style.display = '';
            }
        });
    }

    async function toggleItem(itemPath, isChecked) {
        syncStatus.textContent = "正在同步大屏内容...";
        try {
            await fetch('/web/vision/present/sync', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: isChecked ? 'add' : 'remove', item: itemPath })
            });
            syncStatus.textContent = "大屏同步成功 ✓";
            setTimeout(() => { if(syncStatus.textContent.includes('成功')) syncStatus.textContent = ""; }, 2000);
        } catch (e) {
            syncStatus.textContent = "同步失败，请重试";
        }
    }

    if (toggle) {
        toggle.addEventListener('change', updateVisibility);
    }
    
    cards.forEach(card => {
        const cb = card.querySelector('.card-selector');
        if (cb) {
            cb.addEventListener('change', () => {
                if (toggle && toggle.checked) updateVisibility();
                const dateInput = card.querySelector('input[name="date"]');
                const fileInput = card.querySelector('input[name="file"]');
                if (dateInput && fileInput) {
                    toggleItem(dateInput.value + '/' + fileInput.value, cb.checked);
                }
            });
        }
    });
});
</script>
"""
        else:
            filter_toggle_html = """
<script>
document.addEventListener('DOMContentLoaded', () => {
    const cards = document.querySelectorAll('.grid .card');
    let draggedBox = null;
    
    cards.forEach(box => {
        box.addEventListener('dragstart', (e) => {
            draggedBox = box;
            box.style.opacity = '0.5';
            e.dataTransfer.effectAllowed = 'move';
        });
        
        box.addEventListener('dragend', (e) => {
            box.style.opacity = '1';
            draggedBox = null;
            document.querySelectorAll('.grid .card').forEach(c => c.style.border = '');
            saveNewOrder();
        });
        
        box.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
        });
        
        box.addEventListener('dragenter', (e) => {
            e.preventDefault();
            if (box !== draggedBox) {
                box.style.border = '2px dashed #1890ff';
            }
        });
        
        box.addEventListener('dragleave', (e) => {
            if (box !== draggedBox) {
                box.style.border = '';
            }
        });
        
        box.addEventListener('drop', (e) => {
            e.preventDefault();
            box.style.border = '';
            if (box !== draggedBox && draggedBox) {
                let grid = box.parentNode;
                let all = Array.from(grid.querySelectorAll('.card'));
                let draggedIdx = all.indexOf(draggedBox);
                let targetIdx = all.indexOf(box);
                
                if (draggedIdx < targetIdx) {
                    grid.insertBefore(draggedBox, box.nextSibling);
                } else {
                    grid.insertBefore(draggedBox, box);
                }
            }
        });
    });
    
    async function saveNewOrder() {
        const selected = [];
        document.querySelectorAll('.grid .card').forEach(card => {
            const h = card.querySelector('.card-path-data');
            if (h && h.value) {
                selected.push(h.value);
            }
        });
        try {
            await fetch('/web/vision/present/sync', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ items: selected })
            });
        } catch (e) {
            console.error("顺序同步失败", e);
        }
    }
});
</script>
"""

        body = (
            f"<p>已选日期：{', '.join(selected_dates)} &nbsp; <small>支持多选，或使用 ?dates=YYYYMMDD,YYYYMMDD</small></p>"
            + chat_html
            + sid_datalist_html
            + filter_toggle_html
            + "\n<div class=grid>"
            + "\n".join(cards)
            + "</div>"
        )
        return _html_page("视觉分析结果展示" if is_present else "视觉记录", body)

    async def generated_list(self, request: web.Request) -> web.Response:
        return await self._render_generated_page(request, is_present=False)


    async def generated_present(self, request: web.Request) -> web.Response:
        """纯净展示模式，仅展示选中的生成图片记录"""
        return await self._render_generated_page(request, is_present=True)


    async def _render_generated_page(self, request: web.Request, is_present: bool = False) -> web.Response:
        # 支持日期与学号多选（GET 参数）：date=YYYYMMDD 或 dates=...（可多值/逗号分隔），sids=...
        today = datetime.now().strftime("%Y%m%d")
        def _collect_multi(query, key):
            vals = []
            try:
                arr = query.getall(key)  # 多值
            except Exception:
                arr = []
            if arr:
                for v in arr:
                    for p in (v or "").split(","):
                        p = p.strip()
                        if p:
                            vals.append(p)
            else:
                one = query.get(key) or ""
                if one:
                    for p in one.split(","):
                        p = p.strip()
                        if p:
                            vals.append(p)
            return vals

        selected_dates = _collect_multi(request.query, "dates") or ([request.query.get("date").strip()] if (request.query.get("date")) else [today])
        selected_classes = _collect_multi(request.query, "classes")
        selected_sids = _collect_multi(request.query, "sids")
        sid_keyword = request.query.get("sid_keyword", "").strip()
        filter_class_time = request.query.get("class_time") == "1"
        now_ts = time.time()
        
        recent_dates = [(datetime.now() - timedelta(days=i)).strftime("%Y%m%d") for i in range(0, 30)]

        # 聚合条目（当前筛选范围）
        items = []
        # 学号候选（扫描最近30天全部记录，便于下拉列表完整）
        all_sids = set()
        
        allowed_paths = None
        ordered_items_list = []
        
        # 无论是否 is_present，都读取大屏显示的状态，以便复原勾选框
        state_file = _safe_join(self.data_root, "generated_images", "present_state.json")
        if os.path.exists(state_file):
            import json as _json
            try:
                with open(state_file, "r", encoding="utf-8") as f:
                    jdata = _json.load(f)
                    ordered_items_list = jdata.get("items", [])
                    allowed_paths = set(ordered_items_list)
            except Exception:
                pass
        if allowed_paths is None:
            allowed_paths = set()

        for d in selected_dates:
            vdir = _safe_join(self.data_root, "generated_images", d)
            if not os.path.isdir(vdir):
                continue
            for name in sorted(os.listdir(vdir)):
                if name.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff")):
                    img_real_path = os.path.join(vdir, name)
                    if filter_class_time:
                        try:
                            if abs(now_ts - os.path.getmtime(img_real_path)) > 1800:
                                continue
                        except Exception:
                            pass
                    
                    if is_present and f"{d}/{name}" not in allowed_paths:
                        continue
                    base = name.rsplit(".", 1)[0]
                    json_path = os.path.join(vdir, base + ".json")
                    sid = None
                    try:
                        if os.path.isfile(json_path):
                            import json as _json
                            with open(json_path, "r", encoding="utf-8") as jf:
                                data = _json.load(jf)
                            if isinstance(data, dict):
                                sid = (data.get("student_id") or "").strip()
                        else:
                            meta_path2 = os.path.join(self.data_root, "generated_images", "_meta", d, base + ".json")
                            if os.path.isfile(meta_path2):
                                import json as _json
                                with open(meta_path2, "r", encoding="utf-8") as jf:
                                    meta = _json.load(jf)
                                sid = (meta.get("student_id") or "").strip()
                    except Exception:
                        sid = None
                    json_path = os.path.join(vdir, base + ".json")
                    sid = None
                    try:
                        if os.path.isfile(json_path):
                            import json as _json
                            with open(json_path, "r", encoding="utf-8") as jf:
                                data = _json.load(jf)
                            if isinstance(data, dict):
                                sid = (data.get("student_id") or "").strip()
                    except Exception:
                        sid = None
                    items.append({
                        "date": d,
                        "img": f"/static/generated_images/{d}/{name}",
                        "json": f"/static/generated_images/{d}/{base}.json",
                        "file": name,
                        "sid": sid,
                    })

        # 补充学号候选：扫描所选日期下的所有 JSON 文件，只显示所选日期有记录的学号
        try:
            for d in selected_dates:
                vdir = _safe_join(self.data_root, "generated_images", d)
                if not os.path.isdir(vdir):
                    continue
                for name in os.listdir(vdir):
                    if not name.lower().endswith(".json"):
                        continue
                    
                    if filter_class_time:
                        try:
                            if abs(now_ts - os.path.getmtime(os.path.join(vdir, name))) > 1800:
                                continue
                        except Exception:
                            pass
                            
                    try:
                        import json as _json
                        with open(os.path.join(vdir, name), "r", encoding="utf-8") as jf:
                            data = _json.load(jf)
                        if isinstance(data, dict):
                            sid = (data.get("student_id") or "").strip()
                            if sid:
                                all_sids.add(sid)
                    except Exception:
                        continue
        except Exception:
            pass

        all_classes = set()
        all_student_suffixes = set()
        for s in all_sids:
            if s and len(s) >= 2 and s[:2].isdigit():
                all_classes.add(s[:2])
            if s and len(s) > 2:
                all_student_suffixes.add(s[2:])
            else:
                all_student_suffixes.add(s)

        if selected_classes:
            items = [it for it in items if any((it.get("sid") or "").startswith(c) for c in selected_classes)]

        if selected_sids:
            items = [it for it in items if any((it.get("sid") or "") == s or (it.get("sid") or "").endswith(s) for s in selected_sids)]

        if sid_keyword:
            items = [it for it in items if sid_keyword in (it.get("sid") or "")]

        cards = []
        sel_options = ["<option value=''>不使用图片</option>"]
        for it in reversed(items[-200:]):
            sel_options.append(f"<option value='{it['date']}/{it['file']}'>{it['date']} · {it['file']}</option>")

        date_opts_html = []
        for d in recent_dates:
            sel = " selected" if d in selected_dates else ""
            date_opts_html.append(f"<option value='{d}'{sel}>{d}</option>")
        # 不再合并所有本地已知学号，只显示当前所选日期下的班级和学号
        # try:
        #     for s in _list_known_sids():
        #         if s:
        #             all_sids.add(s)
        #             if len(s) >= 2 and s[:2].isdigit():
        #                 all_classes.add(s[:2])
        # except Exception:
        #     pass
            
        class_opts_html = []
        for c in sorted(all_classes):
            sel = " selected" if c in selected_classes else ""
            class_opts_html.append(f"<option value='{c}'{sel}>{c}</option>")
            
        sid_opts_html = []
        for s in sorted(all_student_suffixes):
            sel = " selected" if s in selected_sids else ""
            sid_opts_html.append(f"<option value='{s}'{sel}>{s}</option>")
        sid_fallback_html = "" if sid_opts_html else "<input name=\"sids\" type=\"text\" placeholder=\"手动输入后2位或完整学号\" style=\"width:180px;\" />"

        class_time_checked = "checked" if filter_class_time else ""
        selected_dates_str = ",".join(selected_dates)
        selected_classes_str = ",".join(selected_classes)
        selected_sids_str = ",".join(selected_sids)
        form_action = "/web/generated/present" if is_present else "/web/generated"

        chat_html = """
<section id="chat-box" class="card">
    <div class="meta">连续对话（可多选图片参与理解，按 Ctrl/Shift 多选）</div>
    <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin:6px 0;">
        <form id="filter-form" method="get" action="{form_action}" style="display:flex; gap:12px; align-items:center; flex-wrap:wrap;">
            <label class="meta">
                <input type="checkbox" name="class_time" value="1" {class_time_checked} style="transform: scale(1.2); margin-right: 4px;" /> 当堂课时(即时前后半小时)
            </label>
            <label class="meta">日期(多选):
                <select name="dates" id="filter-dates" multiple size="5">{date_opts}</select>
            </label>
            <label class="meta">班级(前2位):
                <select name="classes" id="filter-classes" multiple size="5">{class_opts}</select>
            </label>
            <label class="meta">学号(多选):
                <select name="sids" id="filter-sids" multiple size="5">{sid_opts}</select>
            </label>
            <label class="meta">或者搜索学号关键字:
                <input type="text" name="sid_keyword" value="{sid_keyword}" placeholder="例如: 03或0301" style="width:130px;" />
            </label>
            {sid_fallback}
            <button type="submit">应用筛选</button>
        </form>
        <input id="chat-dates" type="hidden" value="{selected_dates_str}" />
        <label class="meta">图片: <select id="chat-images" multiple size="6">{options}</select></label>
        <label class="meta">学号: <input id="chat-student-id" type="text" placeholder="可选(逗号分隔)" style="width:160px;" value="{selected_sids_str}" /></label>
        <button id="chat-clear" type="button">清空对话</button>
        <span id="chat-status" class="meta"></span>
        <input id="chat-source" type="hidden" value="generated" />
        <label class="meta">录音秒数: <input id="chat-record-seconds" type="number" min="1" max="30" value="3" style="width:64px;" /></label>
        <label class="meta">多图上限: <input id="chat-max-images" type="number" min="1" max="50" value="6" style="width:64px;" /></label>
    </div>
    <div id="chat-messages" style="max-height:300px; overflow:auto; background:#fafafa; padding:8px; border-radius:6px; border:1px solid #eee;"></div>
    <div style="display:flex; gap:8px; align-items:center; margin-top:8px;">
        <input id="chat-input" type="text" placeholder="输入你的问题，回车发送" style="flex:1 1 auto; padding:6px 8px;" />
        <button id="chat-voice" type="button">🎤 语音输入</button>
        <button id="chat-send" type="button">发送</button>
    </div>
    <style>
        .chat-item{{ display:flex; gap:8px; padding:6px 4px; }}
        .chat-item .chat-role{{ width:48px; color:#888; font-size:12px; flex:0 0 auto; }}
        .chat-item .chat-content{{ white-space:pre-wrap; }}
    </style>
</section>
""".format(
            date_opts=''.join(date_opts_html),
            class_opts=''.join(class_opts_html),
            sid_opts=''.join(sid_opts_html),
            options=''.join(sel_options),
            selected_dates_str=selected_dates_str,
            selected_sids_str=selected_sids_str,
            sid_keyword=sid_keyword,
            sid_fallback=sid_fallback_html,
            class_time_checked=class_time_checked,
            form_action=form_action,
        )

        # 学号候选 datalist（供再次分析表单使用）
        sid_datalist_html = "" if not all_sids else ("<datalist id=\"sid-list\">" + "".join([f"<option value='{s}'></option>" for s in sorted(all_sids)]) + "</datalist>")

        if not items:
            cards.append(f"<p>暂无记录（日期：{', '.join(selected_dates)}）。</p>")
        else:
            display_items = list(reversed(items))
            if is_present and ordered_items_list:
                item_dict = {f"{it['date']}/{it['file']}": it for it in display_items}
                display_items = [item_dict[p] for p in ordered_items_list if p in item_dict]
                
            for it in display_items:
                card_extra = ""
                draggable_attr = ""
                
                if is_present:
                    draggable_attr = 'draggable="true"'
                    card_extra = f"""<input type="hidden" class="card-path-data" value="{it['date']}/{it['file']}" />"""
                else:
                    checked_attr = 'checked' if f"{it['date']}/{it['file']}" in allowed_paths else ''
                    card_extra = f"""
    <div style="margin-bottom: 6px;">
      <label style="cursor: pointer; font-weight: bold; background: #e6f7ff; padding: 4px 8px; border-radius: 4px; display: inline-block;">
        <input type="checkbox" class="card-selector" {checked_attr} style="transform: scale(1.2); margin-right: 6px;" /> 选择展示此记录
      </label>
      <input type="hidden" name="date" value="{it['date']}" />
      <input type="hidden" name="file" value="{it['file']}" />
    </div>"""
                
                cards.append(
                    f"""
<div class="card" {draggable_attr} style="position: relative;">
{card_extra}
  <img class="thumb" src="{it['img']}" alt="img" />
  <div class="meta">日期: {it['date']} · 文件: {it['file']}{(' · 学号: '+it['sid']) if it.get('sid') else ''}</div>
  <details>
    <summary>查看分析 JSON</summary>
    <div class="json"><a href="{it['json']}" target="_blank">在新窗口打开</a></div>
  </details>
  
    <form method="post" action="/web/generated/delete" onsubmit="return confirm('确认删除该记录（图片及JSON）？');" style="margin-top:6px;">
        <input type="hidden" name="date" value="{it['date']}" />
        <input type="hidden" name="file" value="{it['file']}" />
        <button type="submit" style="background:#ff4d4f;color:#fff;border-color:#ff4d4f;" class="btn">删除</button>
    </form>
</div>
"""
                )

        filter_toggle_html = ""
        if not is_present:
            filter_toggle_html = """
<div style="margin: 10px 0; padding: 10px; background: #fff; border: 1px solid #ddd; border-radius: 6px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); display: flex; gap: 15px; align-items: center; flex-wrap: wrap;">
  <label style="font-weight: bold; cursor: pointer; font-size: 15px; color: #d9363e;">
    <input type="checkbox" id="toggle-selected-only" style="transform: scale(1.3); margin-right: 8px;" /> 仅展示选中的结果 (当前页)
  </label>
  <a href="/web/generated/present" target="_blank" class="btn btn-primary" style="padding: 4px 12px; border-radius: 4px; text-decoration: none;">打开大屏展示页</a>
  <span id="sync-status" style="color: #888; font-size: 13px;"></span>
</div>
<script>
document.addEventListener('DOMContentLoaded', () => {
    const toggle = document.getElementById('toggle-selected-only');
    const cards = document.querySelectorAll('.grid .card');
    const syncStatus = document.getElementById('sync-status');
    
    function updateVisibility() {
        const onlySelected = toggle.checked;
        cards.forEach(card => {
            const cb = card.querySelector('.card-selector');
            if (!cb) return;
            if (onlySelected && !cb.checked) {
                card.style.display = 'none';
            } else {
                card.style.display = '';
            }
        });
    }

    async function toggleItem(itemPath, isChecked) {
        syncStatus.textContent = "正在同步大屏内容...";
        try {
            await fetch('/web/generated/present/sync', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: isChecked ? 'add' : 'remove', item: itemPath })
            });
            syncStatus.textContent = "大屏同步成功 ✓";
            setTimeout(() => { if(syncStatus.textContent.includes('成功')) syncStatus.textContent = ""; }, 2000);
        } catch (e) {
            syncStatus.textContent = "同步失败，请重试";
        }
    }

    if (toggle) {
        toggle.addEventListener('change', updateVisibility);
    }
    
    cards.forEach(card => {
        const cb = card.querySelector('.card-selector');
        if (cb) {
            cb.addEventListener('change', () => {
                if (toggle && toggle.checked) updateVisibility();
                const dateInput = card.querySelector('input[name="date"]');
                const fileInput = card.querySelector('input[name="file"]');
                if (dateInput && fileInput) {
                    toggleItem(dateInput.value + '/' + fileInput.value, cb.checked);
                }
            });
        }
    });
});
</script>
"""
        else:
            filter_toggle_html = """
<script>
document.addEventListener('DOMContentLoaded', () => {
    const cards = document.querySelectorAll('.grid .card');
    let draggedBox = null;
    
    cards.forEach(box => {
        box.addEventListener('dragstart', (e) => {
            draggedBox = box;
            box.style.opacity = '0.5';
            e.dataTransfer.effectAllowed = 'move';
        });
        
        box.addEventListener('dragend', (e) => {
            box.style.opacity = '1';
            draggedBox = null;
            document.querySelectorAll('.grid .card').forEach(c => c.style.border = '');
            saveNewOrder();
        });
        
        box.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
        });
        
        box.addEventListener('dragenter', (e) => {
            e.preventDefault();
            if (box !== draggedBox) {
                box.style.border = '2px dashed #1890ff';
            }
        });
        
        box.addEventListener('dragleave', (e) => {
            if (box !== draggedBox) {
                box.style.border = '';
            }
        });
        
        box.addEventListener('drop', (e) => {
            e.preventDefault();
            box.style.border = '';
            if (box !== draggedBox && draggedBox) {
                let grid = box.parentNode;
                let all = Array.from(grid.querySelectorAll('.card'));
                let draggedIdx = all.indexOf(draggedBox);
                let targetIdx = all.indexOf(box);
                
                if (draggedIdx < targetIdx) {
                    grid.insertBefore(draggedBox, box.nextSibling);
                } else {
                    grid.insertBefore(draggedBox, box);
                }
            }
        });
    });
    
    async function saveNewOrder() {
        const selected = [];
        document.querySelectorAll('.grid .card').forEach(card => {
            const h = card.querySelector('.card-path-data');
            if (h && h.value) {
                selected.push(h.value);
            }
        });
        try {
            await fetch('/web/generated/present/sync', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ items: selected })
            });
        } catch (e) {
            console.error("顺序同步失败", e);
        }
    }
});
</script>
"""

        body = (
            f"<p>已选日期：{', '.join(selected_dates)} &nbsp; <small>支持多选，或使用 ?dates=YYYYMMDD,YYYYMMDD</small></p>"
            + chat_html
            + sid_datalist_html
            + filter_toggle_html
            + "\n<div class=grid>"
            + "\n".join(cards)
            + "</div>"
        )
        return _html_page("生成图片分析结果展示" if is_present else "生成图片记录", body)



    async def generated_analyze(self, request: web.Request) -> web.Response:
        """生成内容分析页：支持按日期与学号筛选，选择已生成图片进行提问分析。"""
        today = datetime.now().strftime("%Y%m%d")
        def _collect_multi(query, key):
            vals = []
            try:
                arr = query.getall(key)
            except Exception:
                arr = []
            if arr:
                for v in arr:
                    for p in (v or "").split(","):
                        p = p.strip()
                        if p:
                            vals.append(p)
            else:
                one = query.get(key) or ""
                if one:
                    for p in one.split(","):
                        p = p.strip()
                        if p:
                            vals.append(p)
            return vals

        selected_dates = _collect_multi(request.query, "dates") or ([request.query.get("date").strip()] if (request.query.get("date")) else [today])
        recent_dates = [(datetime.now() - timedelta(days=i)).strftime("%Y%m%d") for i in range(0, 30)]

        # 聚合候选：已生成图片 + 学号列表
        items = []
        all_sids = set()
        # 学号来源：视觉记录JSON + 本地已知 + 生成图片元数据(_meta回退)
        try:
            for d in recent_dates:
                vdir = _safe_join(self.data_root, "vision_records", d)
                if os.path.isdir(vdir):
                    for name in os.listdir(vdir):
                        if name.lower().endswith('.json'):
                            try:
                                import json as _json
                                with open(os.path.join(vdir, name), 'r', encoding='utf-8') as jf:
                                    data = _json.load(jf)
                                sid = (data.get('student_id') or '').strip()
                                if sid:
                                    all_sids.add(sid)
                            except Exception:
                                pass
        except Exception:
            pass
        try:
            for s in _list_known_sids():
                if s:
                    all_sids.add(s)
        except Exception:
            pass

        for d in selected_dates:
            gdir = _safe_join(self.data_root, "generated_images", d)
            if not os.path.isdir(gdir):
                continue
            for name in sorted(os.listdir(gdir)):
                if not name.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp")):
                    continue
                # 读取学号（同名json或_meta回退）
                sid = ""
                try:
                    base = name.rsplit('.', 1)[0]
                    meta_path = os.path.join(gdir, base + ".json")
                    if os.path.isfile(meta_path):
                        import json as _json
                        with open(meta_path, 'r', encoding='utf-8') as jf:
                            meta = _json.load(jf)
                        sid = (meta.get('student_id') or '').strip()
                    else:
                        meta_path2 = os.path.join(self.data_root, "generated_images", "_meta", d, base + ".json")
                        if os.path.isfile(meta_path2):
                            import json as _json
                            with open(meta_path2, 'r', encoding='utf-8') as jf:
                                meta = _json.load(jf)
                            sid = (meta.get('student_id') or '').strip()
                except Exception:
                    sid = ""
                if sid:
                    all_sids.add(sid)
                items.append({
                    "date": d,
                    "file": name,
                    "img": f"/static/generated_images/{d}/{name}",
                    "sid": sid,
                })

        # 构建筛选与对话区域
        date_opts_html = []
        for d in recent_dates:
            sel = " selected" if d in selected_dates else ""
            date_opts_html.append(f"<option value='{d}'{sel}>{d}</option>")
        sid_select_options = ["<option value=''>不选择</option>"]
        for s in sorted(all_sids):
            sid_select_options.append(f"<option value='{s}'>{s}</option>")
        sel_options = ["<option value=''>不使用图片</option>"]
        for it in reversed(items[-300:]):
            sel_options.append(f"<option value='{it['date']}/{it['file']}'>{it['date']} · {it['file']}</option>")

        chat_template = """
<section id="chat-box" class="card">
  <div class="meta">生成内容分析（可多选生成图片参与理解，按 Ctrl/Shift 多选）</div>
  <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin:6px 0;">
    <form id="filter-form" method="get" action="/web/generated/analyze" style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
      <label class="meta">日期(多选):
        <select name="dates" id="filter-dates" multiple size="5">{date_opts}</select>
      </label>
      <button type="submit">应用筛选</button>
    </form>
    <input id="chat-dates" type="hidden" value="{selected_dates_str}" />
    <label class="meta">图片: <select id="chat-images" multiple size="8">{options}</select></label>
    <label class="meta">学号:
      <select id="chat-student-id" style="width:180px;">{sid_select_opts}</select>
    </label>
    <button id="chat-clear" type="button">清空结果</button>
    <span id="chat-status" class="meta"></span>
    <input id="chat-source" type="hidden" value="generated" />
  </div>
  <div id="chat-messages" style="max-height:320px; overflow:auto; background:#fafafa; padding:8px; border-radius:6px; border:1px solid #eee;"></div>
  <div style="display:flex; gap:8px; align-items:center; margin-top:8px;">
    <input id="chat-input" type="text" placeholder="输入你的问题，例如：请用一句话描述图片" style="flex:1 1 auto; padding:6px 8px;" />
    <button id="chat-send" type="button">分析</button>
  </div>
</section>
<script>
(function(){
  const msgs = document.getElementById('chat-messages');
  const inp = document.getElementById('chat-input');
  const btn = document.getElementById('chat-send');
  const sel = document.getElementById('chat-images');
  const stu = document.getElementById('chat-student-id');
  const dates = document.getElementById('chat-dates');
  const status = document.getElementById('chat-status');
  const src = document.getElementById('chat-source');
    let convId = null;
    try{ convId = localStorage.getItem('xiaozhi_conv_id_generated') || null; }catch(_){}
  function add(role, text){
    const wrap = document.createElement('div'); wrap.className='chat-item ' + role;
    const who = document.createElement('div'); who.className='chat-role'; who.textContent = role==='user'?'你':'助手';
    const body = document.createElement('div'); body.className='chat-content'; body.textContent=text;
    wrap.appendChild(who); wrap.appendChild(body); msgs.appendChild(wrap); msgs.scrollTop = msgs.scrollHeight;
  }
    document.getElementById('chat-clear').addEventListener('click', ()=>{ msgs.innerHTML=''; status.textContent=''; try{ localStorage.removeItem('xiaozhi_conv_id_generated'); }catch(_){} convId = null; });
  async function send(){
    const q=(inp.value||'').trim(); if(!q) return; add('user', q); inp.value=''; status.textContent='分析中…'; btn.disabled=true;
    const files=[]; for(const o of Array.from(sel.selectedOptions)){ if(o.value) files.push(o.value); }
    const sid = (stu && stu.value)?stu.value.trim():''; if (sid){ try{ localStorage.setItem('xiaozhi_student_id', sid); }catch(_){} }
    try{
            if (!convId){ convId = (Date.now().toString(36) + Math.random().toString(36).slice(2,8)); try{ localStorage.setItem('xiaozhi_conv_id_generated', convId); }catch(_){} }
            const payload={ question:q, history:[], date:'', files:files, source:(src?src.value:'generated'), max_images: 8, student_id:sid, conversation_id: convId };
      const resp = await fetch('/web/vision/chat', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) });
      const data = await resp.json();
            if (data && data.success){ add('assistant', data.reply || ''); if (data.conversation_id && (!convId || data.conversation_id!==convId)){ convId = data.conversation_id; try{ localStorage.setItem('xiaozhi_conv_id_generated', convId); }catch(_){} } status.textContent=''; }
      else { status.textContent='失败：' + (data && data.message || '未知错误'); }
    }catch(e){ status.textContent='异常：' + e; } finally { btn.disabled=false; }
  }
  btn.addEventListener('click', send);
  inp.addEventListener('keydown', e=>{ if(e.key==='Enter' && !e.shiftKey){ e.preventDefault(); send(); }});
  try{ const savedSid = localStorage.getItem('xiaozhi_student_id'); if (stu && savedSid) stu.value = savedSid; }catch(_){ }
})();
</script>
<style>
  .chat-item{ display:flex; gap:8px; padding:6px 4px; }
  .chat-item .chat-role{ width:48px; color:#888; font-size:12px; flex:0 0 auto; }
  .chat-item .chat-content{ white-space:pre-wrap; }
</style>
"""
        chat_html = (
            chat_template
            .replace("{date_opts}", ''.join(date_opts_html))
            .replace("{selected_dates_str}", ",".join(selected_dates))
            .replace("{options}", ''.join(sel_options))
            .replace("{sid_select_opts}", ''.join(sid_select_options))
        )

        # 图片预览栅格（非必须，仅便于直观挑选）
        cards = []
        for it in reversed(items[-120:]):
            cards.append(
                f"""
<div class=card>
  <img class=thumb src="{it['img']}" alt="img" />
  <div class=meta>日期:{it['date']} · 文件:{it['file']}{(' · 学号:'+it['sid']) if it.get('sid') else ''}</div>
</div>
"""
            )
        # 历史分析记录（来自 data/analyses/ 按日期筛选）
        history_items = []
        try:
            import json as _json
            for d in selected_dates:
                adir = _safe_join(self.data_root, "analyses", d)
                if not os.path.isdir(adir):
                    continue
                for name in sorted(os.listdir(adir)):
                    if not name.lower().endswith('.json') or name == 'index.jsonl':
                        continue
                    try:
                        with open(os.path.join(adir, name), 'r', encoding='utf-8') as jf:
                            ev = _json.load(jf)
                        if isinstance(ev, dict):
                            history_items.append(ev)
                    except Exception:
                        continue
        except Exception:
            pass
        # 只展示最近 60 条
        history_items = history_items[-60:]
        hist_cards = []
        for ev in reversed(history_items):
            q = (ev.get('question') or '')
            r = (ev.get('reply') or '')
            sid = (ev.get('student_id') or '')
            src = (ev.get('source') or '')
            dt = f"{ev.get('date','')} {ev.get('time','')}"
            files_list = [f for f in (ev.get('files') or []) if f]
            # 构造缩略图预览：优先使用已生成的 thumbs，其次回退原图地址
            thumbs = ev.get('thumbs') or []
            thumb_imgs = []
            if thumbs:
                for t in thumbs[:8]:
                    t = (t or '').strip().lstrip('/')
                    thumb_imgs.append(f"<img class=thumb src='/static/{t}' alt='thumb' style='max-width:120px; height:auto; border-radius:6px;' />")
            else:
                # 回退：根据来源拼接原图静态路径
                subdir = 'generated_images' if src == 'generated' else 'vision_records'
                for ref in files_list[:8]:
                    ref = (ref or '').replace('\\','/')
                    if '/' not in ref:
                        continue
                    d, fn = ref.split('/', 1)
                    thumb_imgs.append(f"<img class=thumb src='/static/{subdir}/{d}/{fn}' alt='img' style='max-width:120px; height:auto; border-radius:6px;' />")
            thumbs_html = "".join(thumb_imgs)
            files_html = ', '.join(files_list)
            # 删除表单（携带日期、时间、来源与已选日期以便删除后跳转）
            del_form = (
                f"<form method='POST' action='/web/analysis/delete' onsubmit=\"return confirm('确定要删除这条分析记录吗？');\" style='margin-top:6px;'>"
                f"<input type='hidden' name='date' value='{ev.get('date','')}'/>"
                f"<input type='hidden' name='time' value='{ev.get('time','')}'/>"
                f"<input type='hidden' name='source' value='{src}'/>"
                f"<input type='hidden' name='dates' value='{','.join(selected_dates)}'/>"
                f"<button type='submit' class='btn btn-danger'>删除</button>"
                f"</form>"
            )
            hist_cards.append(
                f"""
<div class=card>
  <div class=meta>{dt} · 来源:{src}{(' · 学号:'+sid) if sid else ''}</div>
  <div style="display:flex; gap:6px; flex-wrap:wrap; align-items:flex-start;">{thumbs_html}</div>
  <div class=meta>图片: {files_html}</div>
  <div><strong>问</strong>：{q}</div>
  <div><strong>答</strong>：{r}</div>
  {del_form}
</div>
"""
            )

        body = (
            f"<p>已选日期：{', '.join(selected_dates)} &nbsp; <small>支持多选，或使用 ?dates=YYYYMMDD,YYYYMMDD</small></p>" +
            chat_html +
            ("\n<h3>历史分析记录</h3>\n<div class=grid>" + "\n".join(hist_cards) + "</div>" if hist_cards else "") +
            "\n<h3>图片预览</h3>\n<div class=grid>" + "\n".join(cards) + "</div>"
        )
        return _html_page("生成内容分析", body)

    async def analysis_delete(self, request: web.Request) -> web.Response:
        data = await request.post()
        date_str = (data.get("date") or "").strip()
        time_str = (data.get("time") or "").strip()
        source = (data.get("source") or "").strip() or "unknown"
        # 删除后跳回的日期集合（如果缺失则回退为当前记录日期）
        dates_param = (data.get("dates") or "").strip()
        if not date_str or not time_str:
            raise web.HTTPBadRequest(text="缺少参数")
        try:
            # 删除事件 JSON 文件
            json_path = _safe_join(self.data_root, "analyses", date_str, f"{time_str}_{source}.json")
            if os.path.isfile(json_path):
                os.remove(json_path)
            # 删除对应缩略图（前缀匹配 time_*.jpg）
            thumbs_dir = _safe_join(self.data_root, "analyses", date_str, "thumbs")
            if os.path.isdir(thumbs_dir):
                for name in list(os.listdir(thumbs_dir)):
                    if name.startswith(f"{time_str}_") and name.lower().endswith('.jpg'):
                        try:
                            os.remove(os.path.join(thumbs_dir, name))
                        except Exception:
                            pass
        except Exception as e:
            try:
                self.logger.warning(f"删除分析记录失败: {e}")
            except Exception:
                pass
        # 构造跳转地址：优先保留原多选日期
        if dates_param:
            raise web.HTTPFound(location=f"/web/generated/analyze?dates={dates_param}")
        else:
            raise web.HTTPFound(location=f"/web/generated/analyze?dates={date_str}")

    async def vision_present_sync(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            state_file = _safe_join(self.data_root, "vision_records", "present_state.json")
            os.makedirs(os.path.dirname(state_file), exist_ok=True)
            import json as _json
            
            existing_items = []
            if os.path.exists(state_file):
                try:
                    with open(state_file, "r", encoding="utf-8") as f:
                        jdata = _json.load(f)
                        existing_items = jdata.get("items", [])
                except Exception:
                    pass
                    
            if "action" in data:
                action = data.get("action")
                item = data.get("item")
                if action == "add":
                    if item not in existing_items:
                        existing_items.insert(0, item)  # 最新选中的排在最前
                elif action == "remove":
                    if item in existing_items:
                        existing_items.remove(item)
                new_items = existing_items
            else:
                new_items = data.get("items", [])
                
            with open(state_file, "w", encoding="utf-8") as f:
                _json.dump({"items": new_items}, f, ensure_ascii=False)
            return web.json_response({"success": True})
        except Exception as e:
            return web.json_response({"success": False, "message": str(e)})

    async def generated_present_sync(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            state_file = _safe_join(self.data_root, "generated_images", "present_state.json")
            os.makedirs(os.path.dirname(state_file), exist_ok=True)
            import json as _json
            
            existing_items = []
            if os.path.exists(state_file):
                try:
                    with open(state_file, "r", encoding="utf-8") as f:
                        jdata = _json.load(f)
                        existing_items = jdata.get("items", [])
                except Exception:
                    pass
                    
            if "action" in data:
                action = data.get("action")
                item = data.get("item")
                if action == "add":
                    if item not in existing_items:
                        existing_items.insert(0, item)  # 最新选中的排在最前
                elif action == "remove":
                    if item in existing_items:
                        existing_items.remove(item)
                new_items = existing_items
            else:
                new_items = data.get("items", [])
                
            with open(state_file, "w", encoding="utf-8") as f:
                _json.dump({"items": new_items}, f, ensure_ascii=False)
            return web.json_response({"success": True})
        except Exception as e:
            return web.json_response({"success": False, "message": str(e)})



    async def vision_delete(self, request: web.Request) -> web.Response:
        data = await request.post()
        date_str = (data.get("date") or "").strip()
        file_name = (data.get("file") or "").strip()
        if not date_str or not file_name:
            raise web.HTTPBadRequest(text="缺少参数")
        try:
            # 删除图片
            img_path = _safe_join(self.data_root, "vision_records", date_str, file_name)
            if os.path.isfile(img_path):
                os.remove(img_path)
            # 删除同名 JSON
            base = file_name.rsplit(".", 1)[0]
            json_path = _safe_join(self.data_root, "vision_records", date_str, base + ".json")
            if os.path.isfile(json_path):
                os.remove(json_path)
        except Exception as e:
            try:
                self.logger.warning(f"删除视觉记录失败: {e}")
            except Exception:
                pass
        # 返回当前日期列表页
        raise web.HTTPFound(location=f"/web/vision?date={date_str}")

    async def generated_delete(self, request: web.Request) -> web.Response:
        data = await request.post()
        date_str = (data.get("date") or "").strip()
        file_name = (data.get("file") or "").strip()
        if not date_str or not file_name:
            raise web.HTTPBadRequest(text="缺少参数")
        try:
            # 删除图片
            img_path = _safe_join(self.data_root, "generated_images", date_str, file_name)
            if os.path.isfile(img_path):
                os.remove(img_path)
            # 删除同名 JSON（同目录）
            base = file_name.rsplit(".", 1)[0]
            meta_path = _safe_join(self.data_root, "generated_images", date_str, base + ".json")
            if os.path.isfile(meta_path):
                os.remove(meta_path)
            # 备用目录 _meta 下的 JSON
            meta_path2 = _safe_join(self.data_root, "generated_images", "_meta", date_str, base + ".json")
            if os.path.isfile(meta_path2):
                os.remove(meta_path2)
        except Exception as e:
            try:
                self.logger.warning(f"删除生成图片失败: {e}")
            except Exception:
                pass
        # 返回当前日期列表页
        raise web.HTTPFound(location=f"/web/generated?date={date_str}")

    async def re_analyze(self, request: web.Request) -> web.Response:
        data = await request.post()
        date_str = (data.get("date") or "").strip()
        file_name = (data.get("file") or "").strip()
        question = (data.get("question") or "").strip() or "请用一句话描述图片"
        student_id = (data.get("student_id") or "").strip()
        if not date_str or not file_name:
            raise web.HTTPBadRequest(text="缺少参数")

        img_path = _safe_join(self.data_root, "vision_records", date_str, file_name)
        if not os.path.isfile(img_path):
            raise web.HTTPNotFound(text="图片不存在")

        with open(img_path, "rb") as f:
            img_bytes = f.read()
        img_b64 = base64.b64encode(img_bytes).decode("utf-8")

        # 直接使用配置里已选 VLLM 模块调用
        current_config = self.config
        sel = current_config.get("selected_module", {}).get("VLLM")
        if not sel:
            raise web.HTTPBadRequest(text="未配置默认视觉模块")
        vllm_type = (
            sel
            if "type" not in current_config["VLLM"][sel]
            else current_config["VLLM"][sel]["type"]
        )
        vllm = create_instance(vllm_type, current_config["VLLM"][sel])
        # 将学号附加到问题中（与聊天页一致）
        user_prompt = question + (f"（学号：{student_id}）" if student_id else "") + "(请使用中文回复)"
        
        # 修复：将同步阻塞的 VLLM 请求放入线程池执行，避免卡死主线程导致“Request timed out”
        def _run_sync_vision():
             return vllm.response(user_prompt, img_b64)
             
        loop = asyncio.get_running_loop()
        try:
            # 设置较长的超时（60s），避免大模型响应慢导致前端超时
            result = await asyncio.wait_for(
                loop.run_in_executor(None, _run_sync_vision),
                timeout=90.0
            )
        except asyncio.TimeoutError:
            result = "（分析超时，请稍后重试）"
        except Exception as e:
            result = f"（分析发生错误：{e}）"

        # 保存分析记录（来源 vision，单图）
        try:
            self._save_analysis_event(
                source="vision",
                student_id=student_id,
                question=question,
                reply=result,
                files=[f"{date_str}/{file_name}"]
            )
        except Exception:
            pass

        body = f"""
<p>图片：{file_name}（{date_str}）</p>
<img class="thumb" src="/static/vision_records/{date_str}/{file_name}" alt="img" />
<h3>问题</h3>
<div class="json">{question}{('（学号：'+student_id+'）') if student_id else ''}</div>
<h3>结果</h3>
<div class="json">{result}</div>
<p><a href="/web/vision?date={date_str}">返回列表</a></p>
"""
        return _html_page("再次分析结果", body)

    async def vision_chat(self, request: web.Request) -> web.Response:
        # 接收 { question, history?, date?, file?, files? }
        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"success": False, "message": "请求体需要是JSON"})

        question = (payload.get("question") or "").strip()
        if not question:
            return web.json_response({"success": False, "message": "缺少问题"})

        date_str = (payload.get("date") or "").strip()
        file_name = (payload.get("file") or "").strip()
        files = payload.get("files") or ([] if not file_name else [file_name])
        max_images = int(payload.get("max_images") or 6)
        if max_images < 1:
            max_images = 1
        if max_images > 50:
            max_images = 50
        source = (payload.get("source") or "vision").strip()  # vision | generated
        history = payload.get("history") or []
        student_id = (payload.get("student_id") or "").strip()
        conv_id = (payload.get("conversation_id") or "").strip()
        # 文件名安全过滤
        conv_id = "".join([c for c in conv_id if c.isalnum() or c in ("-","_")])

        # 整理历史为文本（简单拼接）
        hist_text_parts = []
        try:
            for m in history[-16:]:
                role = (m.get("role") or "").strip()
                content = (m.get("content") or "").strip()
                if role and content:
                    who = "用户" if role == "user" else "助手"
                    hist_text_parts.append(f"{who}:{content}")
        except Exception:
            hist_text_parts = []
        hist_text = "\n".join(hist_text_parts)

        # 载入配置与VLLM实例
        current_config = self.config
        sel = current_config.get("selected_module", {}).get("VLLM")
        if not sel:
            return web.json_response({"success": False, "message": "未配置默认视觉模块"})
        vllm_type = (
            sel if "type" not in current_config["VLLM"][sel] else current_config["VLLM"][sel]["type"]
        )
        vllm = create_instance(vllm_type, current_config["VLLM"][sel])

        # 统一通过 OpenAI 兼容 client.chat.completions 来支持文本或多模态
        try:
            reply = ""
            messages = []
            for m in history[-16:]:
                r = (m.get("role") or "").strip()
                c = (m.get("content") or "").strip()
                if r in ("user", "assistant") and c:
                    messages.append({"role": r, "content": c})
            user_content = []
            # 文本
            extra_sid = (f"（学号：{student_id}）" if student_id else "")
            user_text = (("\n\n" + hist_text + "\n\n") if hist_text else "") + question + extra_sid + "(请使用中文回复)"
            user_content.append({"type": "text", "text": user_text})
            # 多图
            if files:
                for raw in files[:max_images]:  # 使用前端传入的上限（带服务器侧边界）
                    fname = (raw or "").strip().replace("\\", "/")
                    if not fname:
                        continue
                    # 兼容 "YYYYMMDD/filename" 或旧版（配合 date_str）
                    d = ""
                    fn = ""
                    if "/" in fname:
                        parts = fname.split("/", 1)
                        d, fn = parts[0].strip(), parts[1].strip()
                    else:
                        d, fn = date_str, fname
                    if not d or not fn:
                        continue
                    subdir = "vision_records" if source != "generated" else "generated_images"
                    img_path = _safe_join(self.data_root, subdir, d, fn)
                    if not os.path.isfile(img_path):
                        continue
                    with open(img_path, "rb") as f:
                        img_bytes = f.read()
                    img_b64 = base64.b64encode(img_bytes).decode("utf-8")
                    user_content.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
                    })
            # 如果没有图片，仍是纯文本
            messages.append({"role": "user", "content": user_content if len(user_content) > 1 else user_text})

            client = getattr(vllm, "client", None)
            model = getattr(vllm, "model_name", None)
            
            def _do_chat():
                # 使用90秒超时，防止大模型处理慢
                oc = client.with_options(timeout=90) if getattr(client, "with_options", None) else client
                return oc.chat.completions.create(model=model, messages=messages, stream=False)

            loop = asyncio.get_running_loop()
            resp = await loop.run_in_executor(None, _do_chat)
            reply = resp.choices[0].message.content
        except Exception as e:
            return web.json_response({"success": False, "message": f"对话失败: {e}"})

        # 持久化保存本次分析（可多图，来源 vision/generated）
        try:
            self._save_analysis_event(
                source=source or "vision",
                student_id=student_id,
                question=question,
                reply=reply,
                files=[(f or "").strip() for f in (files or []) if f]
            )
        except Exception:
            pass
        # 追加到会话记录（如果提供了会话ID，或由服务器生成一个）
        try:
            if not conv_id:
                from datetime import datetime as _dt
                conv_id = _dt.now().strftime("%H%M%S") + "-" + os.urandom(3).hex()
            else:
                # 再次兜底过滤
                conv_id = "".join([c for c in conv_id if c.isalnum() or c in ("-","_")]) or (os.urandom(3).hex())
            conv_date = self._append_conversation_event(
                conversation_id=conv_id,
                source=source or "vision",
                student_id=student_id,
                question=question,
                reply=reply,
                files=[(f or "").strip() for f in (files or []) if f]
            )
        except Exception:
            conv_date = None

        return web.json_response({"success": True, "reply": reply, "conversation_id": conv_id, "date": conv_date})

    async def conversations_list(self, request: web.Request) -> web.Response:
        """对话记录列表页：扫描 data/conversations/YYYYMMDD 下的 .jsonl"""
        rows = []
        try:
            conv_root = os.path.join(self.data_root, "conversations")
            if os.path.isdir(conv_root):
                for d in sorted(os.listdir(conv_root)):
                    day_dir = _safe_join(self.data_root, "conversations", d)
                    if not os.path.isdir(day_dir):
                        continue
                    for name in sorted(os.listdir(day_dir)):
                        if not name.lower().endswith('.jsonl'):
                            continue
                        cid = name[:-6]
                        fpath = os.path.join(day_dir, name)
                        try:
                            # 读取前后各一行做摘要
                            first_line = None
                            last_line = None
                            count = 0
                            with open(fpath, 'r', encoding='utf-8') as f:
                                for line in f:
                                    line = line.strip()
                                    if not line:
                                        continue
                                    count += 1
                                    if first_line is None:
                                        first_line = line
                                    last_line = line
                            import json as _json
                            fst = _json.loads(first_line) if first_line else {}
                            lst = _json.loads(last_line) if last_line else {}
                            sid = (lst.get('student_id') or fst.get('student_id') or '')
                            rows.append({
                                'date': d,
                                'id': cid,
                                'count': count,
                                'start': (fst.get('timestamp') or ''),
                                'end': (lst.get('timestamp') or ''),
                                'student_id': sid,
                                'source': (lst.get('source') or fst.get('source') or ''),
                            })
                        except Exception:
                            continue
        except Exception:
            pass
        # 渲染
        cards = []
        if not rows:
            cards.append("<p>暂无对话记录。</p>")
        else:
            for r in reversed(rows[-200:]):
                meta = f"{r['date']} · {r['id']} · 轮次:{r['count']}" + (f" · 学号:{r['student_id']}" if r.get('student_id') else '')
                cards.append(
                    f"""
<div class=card>
  <div class=meta>{meta}</div>
  <div>
    <a class='btn btn-primary' href='/web/conversations/view?date={r['date']}&id={r['id']}'>查看</a>
    <form method='POST' action='/web/conversations/delete' style='display:inline-block; margin-left:8px;' onsubmit=\"return confirm('确认删除该会话？');\">
      <input type='hidden' name='date' value='{r['date']}' />
      <input type='hidden' name='id' value='{r['id']}' />
      <button type='submit' class='btn'>删除</button>
    </form>
  </div>
</div>
"""
                )
        body = "<h3>对话记录</h3>\n<div class=grid>" + "\n".join(cards) + "</div>"
        return _html_page("对话记录", body)

    async def conversations_view(self, request: web.Request) -> web.Response:
        date_str = (request.query.get('date') or '').strip()
        conv_id = (request.query.get('id') or '').strip()
        conv_id = "".join([c for c in conv_id if c.isalnum() or c in ("-","_")])
        if not date_str or not conv_id:
            raise web.HTTPBadRequest(text="缺少参数")
        fpath = _safe_join(self.data_root, "conversations", date_str, f"{conv_id}.jsonl")
        if not os.path.isfile(fpath):
            raise web.HTTPNotFound(text="会话不存在")
        items = []
        try:
            import json as _json
            with open(fpath, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = _json.loads(line)
                        items.append(obj)
                    except Exception:
                        continue
        except Exception:
            pass
        turns = []
        for it in items:
            ts = (it.get('timestamp') or '')
            q = (it.get('question') or '')
            r = (it.get('reply') or '')
            sid = (it.get('student_id') or '')
            src = (it.get('source') or '')
            fl = ', '.join([f for f in (it.get('files') or []) if f])
            turns.append(
                f"""
<div class=card>
  <div class=meta>{ts} · 来源:{src}{(' · 学号:'+sid) if sid else ''}</div>
  <div><strong>问</strong>：{q}</div>
  <div><strong>答</strong>：{r}</div>
  <div class=meta>图片: {fl}</div>
</div>
"""
            )
        actions = (
            f"""
<form method='POST' action='/web/conversations/analyze' style='margin-bottom:8px;'>
  <input type='hidden' name='date' value='{date_str}' />
  <input type='hidden' name='id' value='{conv_id}' />
  <button type='submit' class='btn btn-primary'>分析此对话</button>
</form>
<form method='POST' action='/web/conversations/delete' onsubmit=\"return confirm('确认删除该会话？');\">
  <input type='hidden' name='date' value='{date_str}' />
  <input type='hidden' name='id' value='{conv_id}' />
  <button type='submit' class='btn'>删除</button>
</form>
"""
        )
        body = f"<h3>会话 {conv_id}（{date_str}）</h3>" + actions + "\n".join(turns)
        return _html_page("会话详情", body)

    async def conversations_delete(self, request: web.Request) -> web.Response:
        data = await request.post()
        date_str = (data.get('date') or '').strip()
        conv_id = (data.get('id') or '').strip()
        conv_id = "".join([c for c in conv_id if c.isalnum() or c in ("-","_")])
        if not date_str or not conv_id:
            raise web.HTTPBadRequest(text="缺少参数")
        try:
            fpath = _safe_join(self.data_root, "conversations", date_str, f"{conv_id}.jsonl")
            if os.path.isfile(fpath):
                os.remove(fpath)
        except Exception as e:
            try:
                self.logger.warning(f"删除会话失败: {e}")
            except Exception:
                pass
        raise web.HTTPFound(location="/web/conversations")

    async def conversations_analyze(self, request: web.Request) -> web.Response:
        data = await request.post()
        date_str = (data.get('date') or '').strip()
        conv_id = (data.get('id') or '').strip()
        conv_id = "".join([c for c in conv_id if c.isalnum() or c in ("-","_")])
        if not date_str or not conv_id:
            raise web.HTTPBadRequest(text="缺少参数")
        fpath = _safe_join(self.data_root, "conversations", date_str, f"{conv_id}.jsonl")
        if not os.path.isfile(fpath):
            raise web.HTTPNotFound(text="会话不存在")
        # 汇总文本以供大模型分析
        convo_text = []
        try:
            import json as _json
            with open(fpath, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = _json.loads(line)
                        ts = (obj.get('timestamp') or '')
                        sid = (obj.get('student_id') or '')
                        q = (obj.get('question') or '')
                        r = (obj.get('reply') or '')
                        if q:
                            convo_text.append(f"用户({ts}{(' 学号:'+sid) if sid else ''}): {q}")
                        if r:
                            convo_text.append(f"助手: {r}")
                    except Exception:
                        continue
        except Exception:
            pass
        summary = ""
        try:
            current_config = self.config
            sel = current_config.get("selected_module", {}).get("VLLM")
            if not sel:
                raise RuntimeError("未配置默认视觉/对话模块")
            vllm_type = sel if "type" not in current_config["VLLM"][sel] else current_config["VLLM"][sel]["type"]
            vllm = create_instance(vllm_type, current_config["VLLM"][sel])
            client = getattr(vllm, "client", None)
            model = getattr(vllm, "model_name", None)
            oc = client.with_options(timeout=60) if getattr(client, "with_options", None) else client
            prompt = "\n".join(convo_text[-200:])  # 限制最后200行
            inst = "请对上述对话做一个中文总结，提炼关键信息和后续行动项。"
            messages = [{"role":"user", "content": prompt + "\n\n" + inst}]
            resp = oc.chat.completions.create(model=model, messages=messages, stream=False)
            summary = resp.choices[0].message.content
        except Exception as e:
            summary = f"分析失败: {e}"

        body = f"""
<h3>会话分析</h3>
<div class='card'>
  <div class='meta'>会话: {conv_id} · 日期: {date_str}</div>
  <div class='json'>{summary}</div>
</div>
<p><a href='/web/conversations/view?date={date_str}&id={conv_id}'>返回会话</a> · <a href='/web/conversations'>返回列表</a></p>
"""
        return _html_page("会话分析", body)

    async def conversations_analyze_sids(self, request: web.Request) -> web.Response:
        """根据选择的学号与日期范围，汇总多会话内容进行一次总览分析"""
        data = await request.post()
        dates_param = (data.get('dates') or '').strip()
        sids_param = (data.get('sids') or '').strip()
        custom_prompt = (data.get('prompt') or '').strip()
        if not sids_param:
            raise web.HTTPBadRequest(text="请先在列表页选择学号后再分析")
        selected_sids = [s.strip() for s in sids_param.split(',') if s.strip()]
        if not selected_sids:
            raise web.HTTPBadRequest(text="未提供有效学号")
        if dates_param:
            selected_dates = [d.strip() for d in dates_param.split(',') if d.strip()]
        else:
            selected_dates = [(datetime.now() - timedelta(days=i)).strftime("%Y%m%d") for i in range(0, 30)]

        convo_text = []
        try:
            import json as _json
            for d in selected_dates:
                day_dir = _safe_join(self.data_root, "conversations", d)
                if not os.path.isdir(day_dir):
                    continue
                for name in sorted(os.listdir(day_dir)):
                    if not name.lower().endswith('.jsonl'):
                        continue
                    fpath = os.path.join(day_dir, name)
                    try:
                        with open(fpath, 'r', encoding='utf-8') as f:
                            for line in f:
                                line = line.strip()
                                if not line:
                                    continue
                                try:
                                    obj = _json.loads(line)
                                    sid = (obj.get('student_id') or '').strip()
                                    if sid and sid in selected_sids:
                                        ts = (obj.get('timestamp') or '')
                                        q = (obj.get('question') or '')
                                        r = (obj.get('reply') or '')
                                        if q:
                                            convo_text.append(f"用户({ts} 学号:{sid}): {q}")
                                        if r:
                                            convo_text.append(f"助手: {r}")
                                except Exception:
                                    continue
                    except Exception:
                        continue
        except Exception:
            pass

        if not convo_text:
            body = (
                "<div class='card'><div class='meta'>没有找到匹配所选学号与日期范围的会话记录。</div></div>"
                + f"<p><a href='/web/conversations?dates={','.join(selected_dates)}&sids={','.join(selected_sids)}'>返回列表</a></p>"
            )
            return _html_page("学号会话分析", body)

        # 调用LLM生成总结
        summary = ""
        try:
            current_config = self.config
            sel = current_config.get("selected_module", {}).get("VLLM")
            if not sel:
                raise RuntimeError("未配置默认视觉/对话模块")
            vllm_type = sel if "type" not in current_config["VLLM"][sel] else current_config["VLLM"][sel]["type"]
            vllm = create_instance(vllm_type, current_config["VLLM"][sel])
            client = getattr(vllm, "client", None)
            model = getattr(vllm, "model_name", None)
            oc = client.with_options(timeout=60) if getattr(client, "with_options", None) else client
            # 控制上下文长度：仅取最后 N 行
            prompt = "\n".join(convo_text[-600:])
            base_inst = (
                custom_prompt if custom_prompt else (
                    "请基于上述多位学生的会话片段，分别汇总每个学号的沟通要点、问题主题与下一步建议，并给出整体观察。"
                    "用中文输出，分条列出，注意隐私保护。"
                )
            )
            messages = [{"role":"user", "content": prompt + "\n\n" + base_inst}]
            resp = oc.chat.completions.create(model=model, messages=messages, stream=False)
            summary = resp.choices[0].message.content
        except Exception as e:
            summary = f"分析失败: {e}"

        body = f"""
<h3>学号会话分析</h3>
<div class='card'>
  <div class='meta'>学号: {', '.join(selected_sids)} · 日期: {', '.join(selected_dates)}</div>
  <div class='json'>{summary}</div>
</div>
<p><a href='/web/conversations?dates={','.join(selected_dates)}&sids={','.join(selected_sids)}'>返回列表</a> · <a href='/web/conversations'>重置筛选</a></p>
"""
        return _html_page("学号会话分析", body)

    async def conversations_analyze_selected(self, request: web.Request) -> web.Response:
        """对勾选的若干会话进行合并分析，支持自定义提示词"""
        data = await request.post()
        items_param = (data.get('items') or '').strip()
        custom_prompt = (data.get('prompt') or '').strip()
        if not items_param:
            raise web.HTTPBadRequest(text="请先在列表页勾选会话后再分析")
        # 解析形如 "YYYYMMDD|conversation_id" 的条目
        pairs = []
        for token in items_param.split(','):
            token = (token or '').strip()
            if not token:
                continue
            if '|' not in token:
                continue
            d, cid = token.split('|', 1)
            d = ''.join([c for c in d if c.isdigit()])
            cid = "".join([c for c in cid if c.isalnum() or c in ("-","_")])
            if d and cid:
                pairs.append((d, cid))
        if not pairs:
            raise web.HTTPBadRequest(text="没有可用的会话条目")

        # 读取多会话文本
        convo_text = []
        try:
            import json as _json
            for d, cid in pairs:
                fpath = _safe_join(self.data_root, "conversations", d, f"{cid}.jsonl")
                if not os.path.isfile(fpath):
                    continue
                convo_text.append(f"【会话 {cid} · 日期 {d}】")
                try:
                    with open(fpath, 'r', encoding='utf-8') as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                obj = _json.loads(line)
                                ts = (obj.get('timestamp') or '')
                                sid = (obj.get('student_id') or '').strip()
                                q = (obj.get('question') or '')
                                r = (obj.get('reply') or '')
                                if q:
                                    if sid:
                                        convo_text.append(f"用户({ts} 学号:{sid}): {q}")
                                    else:
                                        convo_text.append(f"用户({ts}): {q}")
                                if r:
                                    convo_text.append(f"助手: {r}")
                            except Exception:
                                continue
                except Exception:
                    continue
        except Exception:
            pass

        if not convo_text:
            body = (
                "<div class='card'><div class='meta'>未能读取到选中会话内容，请重试。</div></div>"
                + "<p><a href='/web/conversations'>返回列表</a></p>"
            )
            return _html_page("选中会话分析", body)

        # 拼接提示词
        base_inst = (
            custom_prompt
            if custom_prompt else
            "请按每个会话梳理问题、关键信息与后续行动项，最后给出总体观察。用中文分条输出，注意隐私保护。"
        )

        summary = ""
        try:
            current_config = self.config
            sel = current_config.get("selected_module", {}).get("VLLM")
            if not sel:
                raise RuntimeError("未配置默认视觉/对话模块")
            vllm_type = sel if "type" not in current_config["VLLM"][sel] else current_config["VLLM"][sel]["type"]
            vllm = create_instance(vllm_type, current_config["VLLM"][sel])
            client = getattr(vllm, "client", None)
            model = getattr(vllm, "model_name", None)
            oc = client.with_options(timeout=60) if getattr(client, "with_options", None) else client
            prompt = "\n".join(convo_text[-800:])
            messages = [{"role":"user", "content": prompt + "\n\n" + base_inst}]
            resp = oc.chat.completions.create(model=model, messages=messages, stream=False)
            summary = resp.choices[0].message.content
        except Exception as e:
            summary = f"分析失败: {e}"

        sel_meta = ", ".join([f"{d}|{cid}" for d, cid in pairs])
        body = f"""
<h3>选中会话分析</h3>
<div class='card'>
  <div class='meta'>会话: {sel_meta}</div>
  <div class='json'>{summary}</div>
</div>
<p><a href='/web/conversations'>返回列表</a></p>
"""
        return _html_page("选中会话分析", body)

    async def conversations_page(self, request: web.Request) -> web.Response:
        """对话记录列表页：支持按日期/学号筛选；支持勾选会话并用自定义提示词调用大模型分析"""
        today = datetime.now().strftime("%Y%m%d")
        def _collect_multi(query, key):
            vals = []
            try:
                arr = query.getall(key)
            except Exception:
                arr = []
            if arr:
                for v in arr:
                    for p in (v or '').split(','):
                        p = (p or '').strip()
                        if p:
                            vals.append(p)
            else:
                one = query.get(key) or ''
                if one:
                    for p in one.split(','):
                        p = (p or '').strip()
                        if p:
                            vals.append(p)
            return vals

        selected_dates = _collect_multi(request.query, 'dates') or ([request.query.get('date').strip()] if (request.query.get('date')) else [today])
        selected_sids = _collect_multi(request.query, 'sids')
        recent_dates = [(datetime.now() - timedelta(days=i)).strftime("%Y%m%d") for i in range(0, 30)]

        rows = []
        all_sids = set()
        try:
            conv_root = os.path.join(self.data_root, "conversations")
            if os.path.isdir(conv_root):
                for d in sorted(os.listdir(conv_root)):
                    if d not in selected_dates:
                        continue
                    day_dir = _safe_join(self.data_root, "conversations", d)
                    if not os.path.isdir(day_dir):
                        continue
                    for name in sorted(os.listdir(day_dir)):
                        if not name.lower().endswith('.jsonl'):
                            continue
                        cid = name[:-6]
                        fpath = os.path.join(day_dir, name)
                        try:
                            first_line = None
                            last_line = None
                            count = 0
                            with open(fpath, 'r', encoding='utf-8') as f:
                                for line in f:
                                    line = line.strip()
                                    if not line:
                                        continue
                                    count += 1
                                    if first_line is None:
                                        first_line = line
                                    last_line = line
                            import json as _json
                            fst = _json.loads(first_line) if first_line else {}
                            lst = _json.loads(last_line) if last_line else {}
                            sid = (lst.get('student_id') or fst.get('student_id') or '').strip()
                            if sid:
                                all_sids.add(sid)
                            rows.append({
                                'date': d,
                                'id': cid,
                                'count': count,
                                'start': (fst.get('timestamp') or ''),
                                'end': (lst.get('timestamp') or ''),
                                'student_id': sid,
                                'source': (lst.get('source') or fst.get('source') or ''),
                            })
                        except Exception:
                            continue
        except Exception:
            pass

        try:
            for s in _list_known_sids():
                if s:
                    all_sids.add(s)
        except Exception:
            pass

        if selected_sids:
            rows = [r for r in rows if (r.get('student_id') or '') in selected_sids]

        date_opts_html = []
        for d in recent_dates:
            sel = " selected" if d in selected_dates else ""
            date_opts_html.append(f"<option value='{d}'{sel}>{d}</option>")
        sid_opts_html = []
        for s in sorted(all_sids):
            sel = " selected" if s in selected_sids else ""
            sid_opts_html.append(f"<option value='{s}'{sel}>{s}</option>")
        sid_fallback_html = "" if sid_opts_html else "<input name=\"sids\" type=\"text\" placeholder=\"手动输入学号(逗号分隔)\" style=\"width:180px;\" />"

        toolbar_tmpl = """
<section class='card'>
  <div class='meta'>可按日期、学号筛选，并对所选学号的会话进行总结分析</div>
  <div style='display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin:6px 0;'>
    <form id='conv-filter' method='get' action='/web/conversations' style='display:flex; gap:8px; align-items:center; flex-wrap:wrap;'>
      <label class='meta'>日期(多选):
        <select name='dates' id='conv-dates' multiple size='5'>{date_opts}</select>
      </label>
      <label class='meta'>学号(多选):
        <select name='sids' id='conv-sids' multiple size='5'>{sid_opts}</select>
      </label>
      {sid_fallback}
      <button type='submit'>应用筛选</button>
    </form>
    <form id='conv-analyze-sids' method='post' action='/web/conversations/analyze_sids' style='display:flex; gap:8px; align-items:center; flex-wrap:wrap;'>
      <input type='hidden' name='dates' id='conv-analyze-dates' value='{selected_dates}' />
      <input type='hidden' name='sids' id='conv-analyze-sids-val' value='{selected_sids}' />
            <label class='meta'>提示词(可选):
                <input type='text' name='prompt' id='conv-analyze-sids-prompt' placeholder='例如：按学号汇总重点与建议，给出总体观察' style='width:320px;' />
            </label>
      <button type='submit' class='btn btn-primary'>分析选中学号</button>
    </form>
  </div>
</section>
<section class='card'>
  <div style='display:flex; gap:8px; align-items:center; flex-wrap:wrap;'>
    <button type='button' id='btn-select-all'>全选</button>
    <button type='button' id='btn-unselect-all'>取消全选</button>
    <button type='button' id='btn-custom-analyze' class='btn btn-primary'>自定义分析…</button>
    <form id='conv-analyze-selected' method='post' action='/web/conversations/analyze_selected' style='display:none;'>
      <input type='hidden' name='items' id='conv-selected-items' value='' />
      <input type='hidden' name='prompt' id='conv-selected-prompt' value='' />
    </form>
  </div>
  <div id='prompt-box' style='display:none; margin-top:8px;'>
    <label class='meta'>分析提示词（可选，自定义对话总结/提炼要求）</label>
    <textarea id='custom-prompt' rows='4' style='width:100%; padding:6px 8px;' placeholder='例如：请按每个会话梳理问题、关键信息、后续行动项，并输出简短要点列表。'></textarea>
    <div style='margin-top:6px; display:flex; gap:8px;'>
      <button type='button' id='btn-submit-selected' class='btn btn-primary'>提交分析</button>
      <button type='button' id='btn-cancel-prompt'>取消</button>
    </div>
  </div>
</section>
<script>
(function(){
  const btnForm = document.getElementById('conv-analyze-sids');
  if (btnForm){
    btnForm.addEventListener('submit', function(e){
      const dSel = document.getElementById('conv-dates');
      const sSel = document.getElementById('conv-sids');
      const dates = []; const sids = [];
      if (dSel){ for (const o of Array.from(dSel.selectedOptions)){ if (o.value) dates.push(o.value); } }
      if (sSel){ for (const o of Array.from(sSel.selectedOptions)){ if (o.value) sids.push(o.value); } }
      document.getElementById('conv-analyze-dates').value = dates.join(',');
      document.getElementById('conv-analyze-sids-val').value = sids.join(',');
    });
  }
  const q = (sel)=>Array.from(document.querySelectorAll(sel));
  const btnAll = document.getElementById('btn-select-all');
  const btnNone = document.getElementById('btn-unselect-all');
  const btnCustom = document.getElementById('btn-custom-analyze');
  const promptBox = document.getElementById('prompt-box');
  const btnSubmitSel = document.getElementById('btn-submit-selected');
  const btnCancel = document.getElementById('btn-cancel-prompt');
  const hiddenItems = document.getElementById('conv-selected-items');
  const hiddenPrompt = document.getElementById('conv-selected-prompt');
  const promptInput = document.getElementById('custom-prompt');
  const formSel = document.getElementById('conv-analyze-selected');
  if (btnAll){ btnAll.addEventListener('click', ()=>{ q('.conv-select').forEach(cb=>{ cb.checked = true; }); }); }
  if (btnNone){ btnNone.addEventListener('click', ()=>{ q('.conv-select').forEach(cb=>{ cb.checked = false; }); }); }
  if (btnCustom){ btnCustom.addEventListener('click', ()=>{ promptBox.style.display = (promptBox.style.display==='none'?'block':'none'); }); }
  if (btnCancel){ btnCancel.addEventListener('click', ()=>{ promptBox.style.display='none'; }); }
  if (btnSubmitSel){ btnSubmitSel.addEventListener('click', ()=>{
    const items = q('.conv-select:checked').map(cb=>cb.value).filter(Boolean);
    if (!items.length){ alert('请先勾选要分析的会话卡片'); return; }
    hiddenItems.value = items.join(',');
    hiddenPrompt.value = (promptInput.value||'').trim();
    formSel.submit();
  }); }
})();
</script>
"""
        toolbar_html = (
            toolbar_tmpl
            .replace("{date_opts}", ''.join(date_opts_html))
            .replace("{sid_opts}", ''.join(sid_opts_html))
            .replace("{sid_fallback}", sid_fallback_html)
            .replace("{selected_dates}", ",".join(selected_dates))
            .replace("{selected_sids}", ",".join(selected_sids))
        )

        cards = []
        if not rows:
            cards.append("<p>暂无对话记录（请调整筛选条件）。</p>")
        else:
            for r in reversed(rows[-200:]):
                meta = f"{r['date']} · {r['id']} · 轮次:{r['count']}" + (f" · 学号:{r['student_id']}" if r.get('student_id') else '')
                card_tmpl = """
<div class='card'>
  <div class='meta'><label><input type='checkbox' class='conv-select' value='{date}|{cid}' /> 选择</label> · {meta}</div>
  <div>
    <a class='btn btn-primary' href='/web/conversations/view?date={date}&id={cid}'>查看</a>
    <form method='POST' action='/web/conversations/delete' style='display:inline-block; margin-left:8px;' onsubmit="return confirm('确认删除该会话？');">
      <input type='hidden' name='date' value='{date}' />
      <input type='hidden' name='id' value='{cid}' />
      <button type='submit' class='btn'>删除</button>
    </form>
  </div>
</div>
"""
                cards.append(
                    card_tmpl.replace('{meta}', meta).replace('{date}', r['date']).replace('{cid}', r['id'])
                )
        body = "<h3>对话记录</h3>" + toolbar_html + "\n<div class=grid>" + "\n".join(cards) + "</div>"
        return _html_page("对话记录", body)
