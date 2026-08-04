# Fact Checking

Use fact checking for claims that could mislead a learner.

## Claims To Extract

Extract:

- Definitions.
- Technical statements.
- Commands and configuration advice.
- Safety claims.
- Legal/medical/financial claims.
- Product/version claims.
- Formulas, dates, benchmarks, and performance claims.
- "Always", "never", "must", "best", and "only" statements.

## Source Priority

Prefer:

1. Official documentation.
2. Standards/specifications.
3. Academic papers or textbooks.
4. Vendor docs.
5. Reputable technical articles.
6. Community posts only when primary sources are unavailable, and mark confidence lower.

## Output Rules

- Do not present unchecked claims as verified facts.
- If browsing is unavailable, mark claims as "not externally verified".
- If video and source conflict, state the conflict directly.
- Cite sources when browsing or source files are used.
- Avoid long quotations; paraphrase and link.

## Correction Labels

Use:

- `正确`: Supported by reliable sources.
- `基本正确但不完整`: Directionally right but missing caveats.
- `有争议`: Sources disagree or context-dependent.
- `疑似错误`: Evidence points against the claim but confidence is not final.
- `错误`: Clearly contradicted by reliable sources.
- `无法核查`: Not enough evidence or no reliable source available.

## Report Shape

```markdown
## [00:12:31] Claim title

视频原说法：

为什么需要核查：

核查结论：

依据：

给学习者的正确理解：
```
