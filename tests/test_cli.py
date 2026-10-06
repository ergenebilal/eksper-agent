from typer.testing import CliRunner
from arac_eksper.cli import app

runner = CliRunner()

def test_app_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Sahibinden Araç Analiz Ajanı" in result.stdout
