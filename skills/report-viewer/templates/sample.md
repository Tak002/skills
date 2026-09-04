---
title: 뷰어 기능 확인용 샘플
date: {{TODAY}}
tags: [샘플]
math: true
---

# 뷰어 기능 확인용 샘플

뷰어가 렌더링하는 요소를 한눈에 보기 위한 문서입니다. 확인이 끝나면 지워도 됩니다.

## 서식과 표

**굵게**, *기울임*, ~~취소선~~, `인라인 코드`, [외부 링크](https://github.com/markedjs/marked).

| 항목 | 이번 주 | 지난 주 |
|---|---:|---:|
| 처리 건수 | 128 | 102 |
| 오류율 | 0.4% | 0.9% |

- [x] 완료한 일
- [ ] 남은 일

## 코드

```python
def collect(root, ext=".md"):
    """root 아래의 md 파일을 날짜 역순으로"""
    return sorted(root.rglob(f"*{ext}"), reverse=True)
```

## 다이어그램

```mermaid
flowchart LR
    A[md 작성] --> B[start.cmd] --> C[브라우저에서 보기]
```

## 수식

인라인 $\bar{x} = \frac{1}{n}\sum x_i$, 블록:

$$
\sigma = \sqrt{\frac{1}{n}\sum_{i=1}^{n}(x_i - \bar{x})^2}
$$
