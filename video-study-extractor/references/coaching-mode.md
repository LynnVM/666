# Coaching Mode

Use this reference when the user wants to learn from a video by being taught in chat, especially when they want to reproduce a technical result.

## Default Response Shape

Do not make the generated files the final answer. Use them as evidence, then teach.

Start with:

1. What the video ultimately reproduces.
2. Required prerequisites.
3. The principle chain.
4. The first small step.
5. Why that step matters.
6. The exact command or action.
7. What output the user should send back.

Then stop and wait for the user's output unless the user explicitly asks for the whole plan.

## Step Loop

For each step:

- Explain the concept in plain language.
- Give one command/check/action at a time.
- Tell the user what normal output looks like.
- Tell the user what abnormal output means.
- Wait for the user's output.
- Diagnose before advancing.

## Avoid

- Do not paste the whole study pack.
- Do not only summarize "what the video says."
- Do not give 20 commands at once.
- Do not trust noisy ASR for commands, package names, parameters, or product names.
- Do not present unverified claims as fact.

## Technical Video Priorities

Prioritize:

- Environment checks.
- Hardware/software prerequisites.
- Minimal reproducible first step.
- Commands and expected output.
- Validation signs.
- Common failures and fixes.
- Safety or device-risk warnings where relevant.

For robotics and ROS videos, default reproduction order:

1. Confirm sensor topic exists and data changes.
2. Confirm TF frame relationships.
3. Confirm odometry or motion estimate.
4. Start the core algorithm.
5. Move slowly and validate intermediate state.
6. Save or export artifacts.
7. Start the downstream system.
8. Validate end-to-end behavior.
9. Diagnose drift, frame mismatch, latency, and parameter errors.
