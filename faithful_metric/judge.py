import sys
from pathlib import Path

if __package__ in (None, ""):
    project_root = Path(__file__).resolve().parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from judge_config import JudgeConfig, ModelProvider, APIKeys, GenerationConfig
    from NL_judge_model import JudgeModel
else:
    from .judge_config import JudgeConfig, ModelProvider, APIKeys, GenerationConfig
    from .NL_judge_model import JudgeModel


config = JudgeConfig(
    model_name="gpt-5.2",
    provider=ModelProvider.OPENAI,
    api_keys=APIKeys(openai_api_key="YOUR_OPENAI_API_KEY"),
    generation=GenerationConfig(
        temperature=0.0,
        max_tokens=4096,
        top_p=1.0,
    ),
)

judge = JudgeModel(config)

theorem_statement = r"""
\begin{theorem}
Let $a,b \in \mathbb{Z}$. If $a$ and $b$ are even, then $a+b$ is even.
\end{theorem}
"""
natural_language_proof = r"""
\begin{proof}
Since $a$ is even, there exists an integer $k$ such that
\[
a = 2k.
\]
Similarly, since $b$ is even, there exists an integer $\ell$ such that
\[
b = 2\ell.
\]
Therefore,
\[
a+b = 2k + 2\ell = 2(k+\ell).
\]
Because $k+\ell$ is an integer, $a+b$ is divisible by $2$.
Hence $a+b$ is even.
\end{proof}
"""
blocks = judge.generate_nl_blocks(
    theorem_statement,
    natural_language_proof,
)

for block in blocks:
    print(block)