from research_retriever import __version__
from research_retriever.cli import build_parser, main


def test_parser_exposes_version() -> None:
    assert __version__ == "0.1.0"
    assert build_parser().prog == "research-retriever"


def test_root_help_is_successful(capsys) -> None:
    assert main([]) == 0
    assert "Discover and organize research papers" in capsys.readouterr().out

