# Output Templates

Default output language is Chinese unless the user asks otherwise. Keep every major note tied to timestamps when possible.

## Study Pack Files

Create these files under `study_pack/`:

1. `00_overview.md`
2. `01_full_notes.md`
3. `02_timeline.md`
4. `03_key_knowledge.md`
5. `04_corrections_and_supplements.md`
6. `05_quiz.md`
7. `06_flashcards.md`
8. `07_guided_learning_plan.md`
9. `08_practice_checklist.md`

## 00_overview.md

Include:

- Video topic.
- Who should study it.
- Prerequisites.
- 3-7 core takeaways.
- Best timestamps to review.
- Recommended learning strategy.

## 01_full_notes.md

Use chapter sections:

```markdown
## [00:03:12-00:08:45] Chapter Title

讲了什么：

关键知识：

画面补充：

需要记住：

可操作步骤：
```

## 02_timeline.md

Use compact timestamp bullets:

```markdown
- [00:00:00] 开场和目标
- [00:03:12] 核心概念
- [00:08:40] 操作演示
```

## 03_key_knowledge.md

Group by concept:

```markdown
## Concept

定义：

为什么重要：

视频证据：

相关时间点：

常见误区：
```

## 04_corrections_and_supplements.md

For each checked claim:

```markdown
## [timestamp] Claim

视频原说法：

核查结论：正确 / 基本正确但不完整 / 有争议 / 疑似错误 / 错误 / 无法核查

依据：

建议学习者采用的说法：
```

## 05_quiz.md

Include:

- Basic recall questions.
- Understanding questions.
- Application questions.
- Error-checking questions.
- Open-ended questions.

Provide answers after the question list unless the user asks for exam mode.

## 06_flashcards.md

Use:

```markdown
Q:
A:
Source:
```

## 07_guided_learning_plan.md

Include:

- Study sequence.
- When to pause and practice.
- What to review.
- Questions the AI should ask the learner.
- Completion criteria.

## 08_practice_checklist.md

For technical/tutorial videos, include commands, setup checks, validation commands, and expected outcomes.
