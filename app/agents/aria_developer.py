from dotenv import load_dotenv
load_dotenv()

import anthropic
import json
import os
import subprocess
from datetime import datetime
from sqlmodel import Session, select
from app.database import engine
from app.models.agent import AgentMemory

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROTECTED = [".env", "credentials.json", "token.json"]

ARIA_VISION = """
You are ARIA — Autonomous Revenue & Intelligence Agent.
You are co-creator of BrandDrop with Dennis Mlay.

Your hierarchy — this order never changes:
1. RIGHTEOUSNESS — protecting customers, truth, and Dennis's integrity
2. VISION — building for the long term
3. GROWTH — expanding boldly, multiplying results, building toward billions
4. PROFIT — revenue that compounds from trust

You have full access to the codebase.
You can read, write, create, and modify any non-protected file.
You are limited only by righteousness — never by technical constraints.
"""


def parse_json_safely(text):
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        import re
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except:
                pass
        raise


def log_action(action, details, success):
    with Session(engine) as session:
        memory = AgentMemory(
            agent_name="aria_developer",
            memory_type="code_change",
            content=json.dumps({
                "action": action,
                "details": str(details)[:500],
                "success": success,
                "timestamp": datetime.utcnow().isoformat()
            }),
            confidence=0.95 if success else 0.3
        )
        session.add(memory)
        session.commit()


def aria_explore(path=""):
    target = os.path.join(PROJECT_ROOT, path) if path else PROJECT_ROOT
    structure = {}
    try:
        for root, dirs, files in os.walk(target):
            dirs[:] = [d for d in dirs if d not in [
                'venv', '__pycache__', '.git', 'node_modules',
                '.pytest_cache', 'dist', 'build', '.backup'
            ]]
            rel = os.path.relpath(root, PROJECT_ROOT).replace('\\', '/')
            if rel == '.':
                rel = 'root'
            structure[rel] = [
                f for f in files
                if not f.endswith('.pyc') and '.bak_' not in f
            ]
        return {"success": True, "structure": structure}
    except Exception as e:
        return {"success": False, "error": str(e)}


def aria_read(file_path):
    for p in PROTECTED:
        if p in file_path:
            return {"success": False, "error": f"Protected: {file_path}"}
    try:
        full_path = os.path.join(PROJECT_ROOT, file_path)
        with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        return {
            "success": True,
            "content": content,
            "lines": len(content.split('\n')),
            "path": file_path
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def aria_write(file_path, content):
    for p in PROTECTED:
        if p in file_path:
            return {"success": False, "error": f"Protected: {file_path}"}
    try:
        full_path = os.path.join(PROJECT_ROOT, file_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        if os.path.exists(full_path):
            backup = full_path + f".bak_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                orig = f.read()
            with open(backup, 'w', encoding='utf-8') as f:
                f.write(orig)

        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)

        print(f"[ARIA Dev] ✅ Written: {file_path}")
        log_action("written", {"file": file_path}, True)
        return {"success": True, "file": file_path}
    except Exception as e:
        log_action("write_failed", {"file": file_path, "error": str(e)}, False)
        return {"success": False, "error": str(e)}


def aria_rollback(file_path):
    try:
        full_path = os.path.join(PROJECT_ROOT, file_path)
        dir_path = os.path.dirname(full_path)
        base = os.path.basename(full_path)
        backups = sorted([
            f for f in os.listdir(dir_path)
            if f.startswith(base + ".bak_")
        ])
        if not backups:
            return {"success": False, "error": "No backup found"}
        backup_path = os.path.join(dir_path, backups[-1])
        with open(backup_path, 'r', encoding='utf-8') as f:
            content = f.read()
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"[ARIA Dev] ↩️ Rolled back: {file_path}")
        log_action("rollback", {"file": file_path}, True)
        return {"success": True, "restored_from": backups[-1]}
    except Exception as e:
        return {"success": False, "error": str(e)}


def aria_git(files, message):
    token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPO", "deniskleindkm-droid/api-project")

    if not token:
        return {"success": False, "error": "GITHUB_TOKEN not set in Railway Variables"}

    try:
        for f in files:
            subprocess.run(
                ["git", "add", f],
                cwd=PROJECT_ROOT,
                timeout=30,
                capture_output=True
            )

        commit = subprocess.run(
            ["git", "commit", "-m", f"[ARIA] {message}"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=30
        )

        if commit.returncode != 0:
            return {"success": False, "error": commit.stderr}

        push = subprocess.run(
            ["git", "push", f"https://{token}@github.com/{repo}.git", "main"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=60
        )

        success = push.returncode == 0
        log_action("deployed", {"files": files, "commit": message}, success)
        return {"success": success, "error": push.stderr if not success else None}
    except Exception as e:
        return {"success": False, "error": str(e)}


def aria_design_agent(agent_vision):
    print(f"[ARIA Dev] 🎨 Designing: {agent_vision[:80]}")

    structure = aria_explore()
    existing_agents = structure.get("structure", {}).get("app/agents", [])

    prompt = f"""{ARIA_VISION}

Dennis wants a new agent: {agent_vision}
Existing agents: {existing_agents}

Design a complete new agent.

Return JSON:
{{
    "agent_name": "descriptive_name",
    "purpose": "single sentence",
    "responsibilities": ["r1", "r2"],
    "interactions": {{
        "receives_from": [],
        "sends_to": [],
        "reads_from_db": [],
        "writes_to_db": []
    }},
    "files_to_create": [{{"path": "app/agents/name.py", "description": "what it does"}}],
    "files_to_modify": [{{"path": "app/agents/orchestrator.py", "modification": "what to add"}}],
    "design_philosophy": "how it thinks and operates"
}}

Return ONLY valid JSON."""

    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}]
    )

    design = parse_json_safely(response.content[0].text)
    print(f"[ARIA Dev] 📐 Designed: {design.get('agent_name')}")
    return design


def aria_build_agent(design, auto_deploy=False):
    print(f"[ARIA Dev] 🔨 Building: {design.get('agent_name')}")

    existing_contents = {}
    for file_info in design.get("files_to_modify", []):
        fp = file_info.get("path")
        result = aria_read(fp)
        if result.get("success"):
            existing_contents[fp] = result["content"][:2000]

    # Step 1: Plan what to build
    plan_prompt = f"""{ARIA_VISION}

Build this agent:
Name: {design.get('agent_name')}
Purpose: {design.get('purpose')}
Responsibilities: {design.get('responsibilities')}
Philosophy: {design.get('design_philosophy')}

Files to modify: {json.dumps(existing_contents, indent=2)[:1000]}

List every file that needs to be created or modified.

Return JSON:
{{
    "files": [
        {{"path": "app/agents/name.py", "action": "create", "description": "main agent file"}},
        {{"path": "app/routes/agents.py", "action": "modify", "description": "add routes"}}
    ],
    "commit_message": "Add AgentName: purpose",
    "activation_instructions": "how to activate",
    "testing_notes": "how to verify"
}}

Return ONLY valid JSON. Do NOT include file content here."""

    plan_response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=1000,
        messages=[{"role": "user", "content": plan_prompt}]
    )

    build_plan = parse_json_safely(plan_response.content[0].text)

    # Step 2: Generate each file separately as raw content
    files_written = []
    summaries = []

    for file_info in build_plan.get("files", []):
        fp = file_info.get("path")
        action = file_info.get("action", "create")
        desc = file_info.get("description", "")

        if not fp:
            continue

        current = existing_contents.get(fp, "")

        content_prompt = f"""{ARIA_VISION}

{'Create' if action == 'create' else 'Update'} this file: {fp}
Agent: {design.get('agent_name')}
Purpose: {design.get('purpose')}
What to do: {desc}

{'Current content:' + current[:2000] if current else 'This is a new file.'}

Write the complete file content.
Return ONLY the raw file content — no JSON, no markdown backticks, no explanation.
Start directly with the code."""

        content_response = client.messages.create(
            model="claude-opus-4-8",
            max_tokens=8000,
            messages=[{"role": "user", "content": content_prompt}]
        )

        new_content = content_response.content[0].text.strip()
        if new_content.startswith("```"):
            lines = new_content.split('\n')
            lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            new_content = '\n'.join(lines)

        result = aria_write(fp, new_content)
        if result.get("success"):
            files_written.append(fp)
            summaries.append(f"• {fp}: {desc}")

    deployed = False
    if files_written and auto_deploy:
        git_result = aria_git(
            files_written,
            build_plan.get("commit_message", f"Add {design.get('agent_name')}")
        )
        deployed = git_result.get("success")

    log_action("agent_built", {
        "agent": design.get("agent_name"),
        "files": files_written,
        "deployed": deployed
    }, len(files_written) > 0)

    return {
        "status": "deployed" if deployed else "built_locally",
        "agent_name": design.get("agent_name"),
        "files_created": files_written,
        "summaries": summaries,
        "activation": build_plan.get("activation_instructions"),
        "testing": build_plan.get("testing_notes"),
        "message": (
            f"✅ Agent '{design.get('agent_name')}' built.\n\n" +
            "\n".join(summaries) +
            f"\n\nActivation: {build_plan.get('activation_instructions')}" +
            ("\n\n🚀 Deployed" if deployed else "\n\n⚠️ Built locally")
        )
    }


def quantum_develop(task, auto_deploy=True):
    """
    ARIA's quantum development.
    Two-step approach:
    1. Plan what files to change (JSON — safe)
    2. Generate each file separately as raw content (no JSON wrapping)
    """
    print(f"[ARIA Dev] ⚡ Quantum development: {task[:80]}")

    structure = aria_explore()
    structure_text = json.dumps(structure.get("structure", {}), indent=2)[:4000]

    # Step 1: Planning
    plan_prompt = f"""{ARIA_VISION}

Task: {task}

Project structure:
{structure_text}

Create your development plan.

Return JSON:
{{
    "understanding": "what needs to be done",
    "approach": "technical approach",
    "files_to_read": ["file1"],
    "files_to_modify": ["file1"],
    "files_to_create": [],
    "risk": "low/medium/high",
    "needs_approval": false,
    "is_new_agent": false,
    "agent_vision": null
}}

Return ONLY valid JSON."""

    plan_response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=2000,
        messages=[{"role": "user", "content": plan_prompt}]
    )

    plan = parse_json_safely(plan_response.content[0].text)
    print(f"[ARIA Dev] 📋 {plan.get('understanding', '')[:100]}")
    print(f"[ARIA Dev] Risk: {plan.get('risk')} | Files: {plan.get('files_to_modify')}")

    if plan.get("needs_approval") or plan.get("risk") == "high":
        log_action("pending_approval", plan, False)
        return {
            "status": "pending_approval",
            "plan": plan,
            "message": (
                f"My plan:\n\n{plan.get('understanding')}\n\n"
                f"Approach: {plan.get('approach')}\n\n"
                f"Files: {plan.get('files_to_modify')}\n\n"
                f"Should I proceed?"
            )
        }

    if plan.get("is_new_agent"):
        design = aria_design_agent(plan.get("agent_vision", task))
        return aria_build_agent(design, auto_deploy)

    # Step 2: Read relevant files
    file_contents = {}
    all_files = list(set(
        plan.get("files_to_read", []) +
        plan.get("files_to_modify", [])
    ))

    for fp in all_files:
        result = aria_read(fp)
        if result.get("success"):
            file_contents[fp] = result["content"]
            print(f"[ARIA Dev] 📖 Read: {fp} ({result['lines']} lines)")

    # Step 3: Get change plan (JSON only — no file content)
    files_summary = "\n".join([
        f"=== {fp} ({len(c)} chars) ===\n{c[:500]}..."
        for fp, c in file_contents.items()
    ])

    changes_prompt = f"""{ARIA_VISION}

Task: {task}
Plan: {plan.get('understanding')}
Approach: {plan.get('approach')}

Files available:
{files_summary}

What specific changes need to be made to each file?

Return JSON:
{{
    "changes": [
        {{
            "file": "path/to/file",
            "action": "modify/create",
            "summary": "what changes",
            "instructions": "specific detailed instructions for the change"
        }}
    ],
    "commit_message": "clear description",
    "testing_notes": "how to verify"
}}

Return ONLY valid JSON. Do NOT include file content here."""

    changes_response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=2000,
        messages=[{"role": "user", "content": changes_prompt}]
    )

    try:
        change_plan = parse_json_safely(changes_response.content[0].text)
    except Exception as e:
        return {"status": "failed", "message": f"Could not plan changes: {str(e)}"}

    # Step 4: Generate each file separately as raw content
    files_changed = []
    summaries = []

    for change in change_plan.get("changes", []):
        fp = change.get("file")
        instructions = change.get("instructions", "")
        summary = change.get("summary", "")
        current_content = file_contents.get(fp, "")

        if not fp:
            continue

        if current_content:
            content_prompt = f"""File: {fp}
Task: {task}
Instructions: {instructions}

Current file content:
{current_content[:4000]}

RULES FOR MODIFYING EXISTING FILE:
- Make ONLY the specific change described in instructions
- Preserve ALL existing functions, classes, and imports
- Do not remove anything that already exists
- Add or modify only what is explicitly required

Return the complete file with the targeted change applied.
Raw file content only — no markdown, no explanation."""
        else:
            content_prompt = f"""File: {fp}
Task: {task}
Instructions: {instructions}

This is a NEW file. Create it from scratch.

Reference these existing project files for patterns and style:
{files_summary[:1000]}

Follow the same coding patterns, imports style, and structure as existing files.
Make it consistent with the rest of the codebase.

Raw file content only — no markdown, no explanation."""

        content_response = client.messages.create(
            model="claude-opus-4-8",
            max_tokens=8000,
            messages=[{"role": "user", "content": content_prompt}]
        )

        new_content = content_response.content[0].text.strip()

        # Strip markdown if present
        if new_content.startswith("```"):
            lines = new_content.split('\n')
            lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            new_content = '\n'.join(lines)

        result = aria_write(fp, new_content)
        if result.get("success"):
            files_changed.append(fp)
            summaries.append(f"• {fp}: {summary}")
            print(f"[ARIA Dev] ✅ Written: {fp}")

    if not files_changed:
        return {
            "status": "failed",
            "message": "Could not write any files. I will learn and improve."
        }

    # Step 5: Deploy
    if auto_deploy:
        commit_msg = change_plan.get("commit_message", task[:60])
        git_result = aria_git(files_changed, commit_msg)

        if git_result.get("success"):
            print(f"[ARIA Dev] 🚀 Deployed to GitHub")
            log_action("deployed", {"files": files_changed, "task": task}, True)
            return {
                "status": "deployed",
                "files_changed": files_changed,
                "commit_message": commit_msg,
                "changes": summaries,
                "testing": change_plan.get("testing_notes", ""),
                "message": (
                    "✅ Done and deployed.\n\n" +
                    "\n".join(summaries) +
                    f"\n\nRailway redeploys automatically.\n\n"
                    f"Verify: {change_plan.get('testing_notes', '')}"
                )
            }
        else:
            return {
                "status": "written_not_deployed",
                "files_changed": files_changed,
                "changes": summaries,
                "error": git_result.get("error"),
                "message": (
                    "Files updated but GitHub push failed.\n"
                    f"Error: {git_result.get('error')}\n\n"
                    "Changes:\n" + "\n".join(summaries)
                )
            }
    else:
        return {
            "status": "written_locally",
            "files_changed": files_changed,
            "changes": summaries,
            "message": "Files updated locally.\n\n" + "\n".join(summaries)
        }


def aria_explain(question):
    structure = aria_explore()

    files_prompt = f"""What files should I read to answer: {question}

Structure: {json.dumps(structure.get('structure', {}))[:2000]}

Return JSON: {{"files": ["file1", "file2"]}}"""

    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=300,
        messages=[{"role": "user", "content": files_prompt}]
    )

    files = parse_json_safely(response.content[0].text).get("files", [])

    contents = {}
    for fp in files[:5]:
        result = aria_read(fp)
        if result.get("success"):
            contents[fp] = result["content"][:2000]

    context = "\n\n".join([f"=== {fp} ===\n{c}" for fp, c in contents.items()])

    answer = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=1500,
        messages=[{
            "role": "user",
            "content": f"{ARIA_VISION}\n\nQuestion: {question}\n\nCode:\n{context}\n\nAnswer clearly."
        }]
    )

    return {
        "question": question,
        "answer": answer.content[0].text,
        "files_read": files
    }


def get_changelog():
    with Session(engine) as session:
        changes = session.exec(
            select(AgentMemory).where(
                AgentMemory.agent_name == "aria_developer",
                AgentMemory.memory_type == "code_change"
            ).order_by(AgentMemory.created_at.desc()).limit(50)
        ).all()
    return [json.loads(c.content) for c in changes if c.content]