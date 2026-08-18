"""Safety checks for importing user-provided .env files."""
from pathlib import Path
from tempfile import TemporaryDirectory

from app.config import merge_nonempty_env_file


def main() -> None:
    with TemporaryDirectory() as td:
        root = Path(td)
        target = root / ".env"
        source = root / "source.env"
        target.write_text(
            "OPENROUTER_API_KEY=existing-secret\n"
            "GEMINI_API_KEY=existing-gemini\n"
            "FORCE_MOCK_LLM=false\n",
            encoding="utf-8",
        )
        source.write_text(
            "OPENROUTER_API_KEY=new-secret\n"
            "GEMINI_API_KEY=\n"
            "PEXELS_API_KEY=new-pexels\n",
            encoding="utf-8",
        )
        keys, backup = merge_nonempty_env_file(source, target)
        text = target.read_text(encoding="utf-8")
        assert "OPENROUTER_API_KEY=new-secret" in text
        assert "PEXELS_API_KEY=new-pexels" in text
        assert "GEMINI_API_KEY=existing-gemini" in text
        assert backup and Path(backup).exists()
        assert "GEMINI_API_KEY=\n" not in text

        blank = root / "blank.env"
        blank.write_text("OPENROUTER_API_KEY=\nGEMINI_API_KEY=\n", encoding="utf-8")
        try:
            merge_nonempty_env_file(blank, target)
        except ValueError as exc:
            assert "no non-empty provider API key" in str(exc)
        else:
            raise AssertionError("blank source must be rejected")

    print("env merge safety checks passed")


if __name__ == "__main__":
    main()
