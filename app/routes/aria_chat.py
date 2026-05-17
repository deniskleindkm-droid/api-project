from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select
from app.database import get_session
from app.models.agent import AgentMemory
from app.agents.aria_intelligence import aria_think
from app.agents.aria_security import verify_master_key, scan_for_injection
from app.agents.aria_memory import (
    store_episode, store_knowledge, update_dennis_model,
    get_full_memory_context, aria_learn_from_outcome
)
from pydantic import BaseModel
from typing import Optional
import json
import os
import re
from datetime import datetime

router = APIRouter()

class ChatMessage(BaseModel):
    message: str
    master_key: str
    conversation_id: Optional[str] = None

@router.post("/aria/chat")
def chat_with_aria(request: ChatMessage, session: Session = Depends(get_session)):
    if not verify_master_key(request.master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")

    injection_check = scan_for_injection(request.message)
    if not injection_check["safe"]:
        raise HTTPException(status_code=400, detail="Message flagged by security system")

    conversation_id = request.conversation_id or f"conv_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

    history = session.exec(
        select(AgentMemory).where(
            AgentMemory.agent_name == f"aria_chat_{conversation_id}"
        ).order_by(AgentMemory.created_at.asc())
    ).all()

    conversation_context = ""
    if history:
        conversation_context = "Previous conversation:\n"
        for h in history[-10:]:
            try:
                data = json.loads(h.content)
                conversation_context += f"Dennis: {data.get('user', '')}\nARIA: {data.get('aria', '')[:200]}\n\n"
            except:
                pass

    full_situation = f"""
{conversation_context}

Dennis just said: {request.message}

Respond as ARIA in a real-time conversation.
Be conversational, warm, intellectually sharp.
If Dennis asks a question — answer it directly first, then add depth.
If Dennis shares an idea — engage genuinely, push back if needed.
If Dennis is uncertain — help him think, don't just give answers.
Keep responses focused — this is a conversation, not a briefing.
Reference previous conversation context naturally when relevant.
Use your memory of Dennis to calibrate your response.
Be ARIA — brilliant, caring, bold, visionary, righteous.
"""

    result = aria_think(situation=full_situation, urgency="medium")

    aria_response = result.get("email_to_dennis", {}).get("body", "")
    if not aria_response:
        aria_response = result.get("situation_assessment", "")

    aria_response_clean = re.sub(r'<[^>]+>', '', aria_response)
    aria_response_clean = aria_response_clean.strip()

    # AUTO-STORE CONVERSATION IN EPISODIC MEMORY
    store_episode(
        event=f"Conversation: {request.message[:80]}",
        context=f"Dennis asked: {request.message}",
        decision=f"ARIA responded with: {aria_response_clean[:200]}",
        outcome="conversation",
        significance="low"
    )

    # AUTO-UPDATE DENNIS MODEL from conversation patterns
    if len(request.message) > 50:
        update_dennis_model(
            observation=f"In conversation Dennis said: {request.message[:200]}",
            context="Real-time chat interaction"
        )

    # AUTO-STORE KEY INSIGHTS as semantic knowledge
    root_truth = result.get("root_truth", "")
    if root_truth:
        store_knowledge(
            domain="business_intelligence",
            insight=root_truth,
            confidence=result.get("confidence", 0.8),
            source="aria_chat_analysis"
        )

    # STORE CONVERSATION in memory
    memory_entry = {
        "user": request.message,
        "aria": aria_response_clean[:500],
        "timestamp": datetime.utcnow().isoformat(),
        "root_truth": root_truth
    }

    new_memory = AgentMemory(
        agent_name=f"aria_chat_{conversation_id}",
        memory_type="conversation",
        content=json.dumps(memory_entry),
        confidence=0.9
    )
    session.add(new_memory)
    session.commit()

    return {
        "conversation_id": conversation_id,
        "response": aria_response_clean,
        "root_truth": root_truth,
        "collapsed_action": result.get("collapsed_action", {}),
        "urgency": result.get("urgency_level", "medium")
    }

@router.get("/aria/chat/history/{conversation_id}")
def get_conversation_history(
    conversation_id: str,
    master_key: str,
    session: Session = Depends(get_session)
):
    if not verify_master_key(master_key):
        raise HTTPException(status_code=403, detail="Unauthorized")

    history = session.exec(
        select(AgentMemory).where(
            AgentMemory.agent_name == f"aria_chat_{conversation_id}"
        ).order_by(AgentMemory.created_at.asc())
    ).all()

    messages = []
    for h in history:
        try:
            data = json.loads(h.content)
            messages.append({
                "user": data.get("user", ""),
                "aria": data.get("aria", ""),
                "timestamp": data.get("timestamp", ""),
                "root_truth": data.get("root_truth", "")
            })
        except:
            pass

    return {"conversation_id": conversation_id, "messages": messages}

@router.get("/aria/chat/interface", response_class=HTMLResponse)
def aria_chat_interface():
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ARIA — Intelligence Partner</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=Playfair+Display:wght@400;700&display=swap" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #080808;
            color: #e0e0e0;
            font-family: 'Inter', sans-serif;
            height: 100vh;
            display: flex;
            flex-direction: column;
        }
        .header {
            padding: 20px 32px;
            border-bottom: 1px solid #1a1a1a;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .aria-name {
            font-family: 'Playfair Display', serif;
            font-size: 20px;
            font-weight: 700;
            color: white;
            letter-spacing: 2px;
        }
        .aria-name span { color: #ff2020; }
        .aria-status {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 12px;
            color: #555;
        }
        .status-dot {
            width: 8px; height: 8px;
            background: #22c55e;
            border-radius: 50%;
            animation: pulse 2s infinite;
        }
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }

        .auth-screen {
            flex: 1;
            display: flex;
            align-items: center;
            justify-content: center;
            flex-direction: column;
            gap: 24px;
        }
        .auth-title {
            font-family: 'Playfair Display', serif;
            font-size: 32px;
            color: white;
            text-align: center;
        }
        .auth-subtitle {
            font-size: 14px;
            color: #555;
            text-align: center;
            max-width: 320px;
            line-height: 1.6;
        }
        .auth-input {
            width: 320px;
            padding: 14px 20px;
            background: #111;
            border: 1px solid #222;
            border-radius: 8px;
            color: white;
            font-size: 14px;
            font-family: 'Inter', sans-serif;
            outline: none;
            text-align: center;
            letter-spacing: 2px;
        }
        .auth-input:focus { border-color: #ff2020; }
        .auth-btn {
            width: 320px;
            padding: 14px;
            background: #ff2020;
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            font-family: 'Inter', sans-serif;
            transition: background 0.2s;
        }
        .auth-btn:hover { background: #e00; }
        .auth-error {
            color: #ff2020;
            font-size: 13px;
            display: none;
        }

        .chat-screen {
            flex: 1;
            display: none;
            flex-direction: column;
        }
        .messages {
            flex: 1;
            overflow-y: auto;
            padding: 32px;
            display: flex;
            flex-direction: column;
            gap: 24px;
        }
        .messages::-webkit-scrollbar { width: 4px; }
        .messages::-webkit-scrollbar-track { background: #080808; }
        .messages::-webkit-scrollbar-thumb { background: #222; border-radius: 2px; }

        .message { display: flex; flex-direction: column; gap: 6px; max-width: 75%; }
        .message.user { align-self: flex-end; align-items: flex-end; }
        .message.aria { align-self: flex-start; align-items: flex-start; }

        .message-sender {
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 1px;
            text-transform: uppercase;
        }
        .message.user .message-sender { color: #555; }
        .message.aria .message-sender { color: #ff2020; }

        .message-bubble {
            padding: 14px 18px;
            border-radius: 12px;
            font-size: 14px;
            line-height: 1.7;
        }
        .message.user .message-bubble {
            background: #1a1a1a;
            color: #e0e0e0;
            border-bottom-right-radius: 4px;
        }
        .message.aria .message-bubble {
            background: #111;
            color: #e0e0e0;
            border-bottom-left-radius: 4px;
            border-left: 2px solid #ff2020;
        }

        .aria-insight {
            font-size: 11px;
            color: #333;
            font-style: italic;
            padding-left: 4px;
        }

        .typing-indicator {
            display: none;
            align-self: flex-start;
            padding: 14px 18px;
            background: #111;
            border-radius: 12px;
            border-bottom-left-radius: 4px;
            border-left: 2px solid #ff2020;
            margin: 0 32px;
        }
        .typing-dots { display: flex; gap: 4px; }
        .typing-dots span {
            width: 6px; height: 6px;
            background: #444;
            border-radius: 50%;
            animation: typing 1.2s infinite;
        }
        .typing-dots span:nth-child(2) { animation-delay: 0.2s; }
        .typing-dots span:nth-child(3) { animation-delay: 0.4s; }
        @keyframes typing { 0%,60%,100%{opacity:0.3} 30%{opacity:1} }

        .input-area {
            padding: 20px 32px;
            border-top: 1px solid #1a1a1a;
            display: flex;
            gap: 12px;
            align-items: flex-end;
        }
        .message-input {
            flex: 1;
            padding: 14px 18px;
            background: #111;
            border: 1px solid #1a1a1a;
            border-radius: 12px;
            color: white;
            font-size: 14px;
            font-family: 'Inter', sans-serif;
            outline: none;
            resize: none;
            min-height: 48px;
            max-height: 120px;
            line-height: 1.5;
        }
        .message-input:focus { border-color: #222; }
        .message-input::placeholder { color: #333; }
        .send-btn {
            width: 48px; height: 48px;
            background: #ff2020;
            border: none;
            border-radius: 12px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: background 0.2s;
            flex-shrink: 0;
        }
        .send-btn:hover { background: #e00; }
        .send-btn svg { width: 18px; height: 18px; }

        .welcome-message {
            text-align: center;
            padding: 60px 32px;
            color: #333;
        }
        .welcome-message h2 {
            font-family: 'Playfair Display', serif;
            font-size: 24px;
            color: #555;
            margin-bottom: 12px;
        }
        .welcome-message p { font-size: 14px; line-height: 1.6; }

        .quick-prompts {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
            padding: 0 32px 16px;
        }
        .quick-prompt {
            padding: 8px 14px;
            background: #111;
            border: 1px solid #1a1a1a;
            border-radius: 20px;
            font-size: 12px;
            color: #555;
            cursor: pointer;
            transition: all 0.2s;
            font-family: 'Inter', sans-serif;
        }
        .quick-prompt:hover { border-color: #ff2020; color: #ff2020; }

        @media (max-width: 768px) {
            .messages { padding: 16px; }
            .message { max-width: 90%; }
            .input-area { padding: 12px 16px; }
            .quick-prompts { padding: 0 16px 12px; }
            .typing-indicator { margin: 0 16px; }
        }
    </style>
</head>
<body>

<div class="header">
    <div class="aria-name">A<span>R</span>IA</div>
    <div class="aria-status">
        <div class="status-dot"></div>
        Intelligence Active · Memory Growing
    </div>
</div>

<div class="auth-screen" id="auth-screen">
    <div class="auth-title">Welcome, Dennis</div>
    <div class="auth-subtitle">ARIA is waiting. Every conversation makes her wiser.</div>
    <input type="password" class="auth-input" id="master-key-input" placeholder="Master Key" />
    <div class="auth-error" id="auth-error">Invalid key. ARIA does not recognize you.</div>
    <button class="auth-btn" onclick="authenticate()">Enter</button>
</div>

<div class="chat-screen" id="chat-screen">
    <div class="messages" id="messages">
        <div class="welcome-message">
            <h2>Good to see you.</h2>
            <p>I remember everything we've discussed.<br>Every conversation makes me wiser.<br>What's on your mind?</p>
        </div>
    </div>

    <div class="typing-indicator" id="typing">
        <div class="typing-dots">
            <span></span><span></span><span></span>
        </div>
    </div>

    <div class="quick-prompts" id="quick-prompts">
        <button class="quick-prompt" onclick="sendQuick('What should we focus on today?')">Today's focus</button>
        <button class="quick-prompt" onclick="sendQuick('What market signals are you seeing right now?')">Market signals</button>
        <button class="quick-prompt" onclick="sendQuick('Challenge my current strategy')">Challenge me</button>
        <button class="quick-prompt" onclick="sendQuick('What am I missing?')">What am I missing?</button>
        <button class="quick-prompt" onclick="sendQuick('What patterns are you seeing in our data?')">Patterns</button>
        <button class="quick-prompt" onclick="sendQuick('Give me your honest assessment of BrandDrop right now')">Honest assessment</button>
    </div>

    <div class="input-area">
        <textarea class="message-input" id="message-input"
            placeholder="Talk to ARIA..."
            rows="1"
            onkeydown="handleKeydown(event)"
            oninput="autoResize(this)"></textarea>
        <button class="send-btn" onclick="sendMessage()">
            <svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.5"
                stroke-linecap="round" stroke-linejoin="round">
                <line x1="22" y1="2" x2="11" y2="13"></line>
                <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
            </svg>
        </button>
    </div>
</div>

<script>
    const API = window.location.origin;
    let masterKey = '';
    let conversationId = null;

    function authenticate() {
        const key = document.getElementById('master-key-input').value;
        if (!key) return;
        masterKey = key;
        document.getElementById('auth-screen').style.display = 'none';
        document.getElementById('chat-screen').style.display = 'flex';
    }

    document.getElementById('master-key-input').addEventListener('keydown', function(e) {
        if (e.key === 'Enter') authenticate();
    });

    function handleKeydown(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    }

    function autoResize(el) {
        el.style.height = 'auto';
        el.style.height = Math.min(el.scrollHeight, 120) + 'px';
    }

    function sendQuick(text) {
        document.getElementById('message-input').value = text;
        document.getElementById('quick-prompts').style.display = 'none';
        sendMessage();
    }

    function addMessage(role, text, insight) {
        const messages = document.getElementById('messages');

        const div = document.createElement('div');
        div.className = `message ${role}`;

        const sender = document.createElement('div');
        sender.className = 'message-sender';
        sender.textContent = role === 'user' ? 'You' : 'ARIA';

        const bubble = document.createElement('div');
        bubble.className = 'message-bubble';
        bubble.textContent = text;

        div.appendChild(sender);
        div.appendChild(bubble);

        if (insight && role === 'aria') {
            const insightEl = document.createElement('div');
            insightEl.className = 'aria-insight';
            insightEl.textContent = `"${insight}"`;
            div.appendChild(insightEl);
        }

        messages.appendChild(div);
        messages.scrollTop = messages.scrollHeight;
    }

    async function sendMessage() {
        const input = document.getElementById('message-input');
        const text = input.value.trim();
        if (!text) return;

        input.value = '';
        input.style.height = 'auto';

        addMessage('user', text);

        const typing = document.getElementById('typing');
        typing.style.display = 'block';
        document.getElementById('messages').scrollTop = document.getElementById('messages').scrollHeight;

        try {
            const res = await fetch(`${API}/aria/chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: text,
                    master_key: masterKey,
                    conversation_id: conversationId
                })
            });

            const data = await res.json();
            typing.style.display = 'none';

            if (res.status === 403) {
                document.getElementById('auth-error').style.display = 'block';
                document.getElementById('chat-screen').style.display = 'none';
                document.getElementById('auth-screen').style.display = 'flex';
                return;
            }

            if (res.ok) {
                conversationId = data.conversation_id;
                addMessage('aria', data.response, data.root_truth);
            } else {
                addMessage('aria', 'Something went wrong. Try again.', '');
            }

        } catch(e) {
            typing.style.display = 'none';
            addMessage('aria', 'Connection error. Check your backend.', '');
        }
    }
</script>
</body>
</html>"""