"""CLI run service — thin wrapper over ApplicationRunService."""

from __future__ import annotations

from pathlib import Path

from kite.application.cli.result import CliResult, format_cli_output
from kite.application.contracts import RunSpec
from kite.application.dependencies import HarnessDependencies
from kite.application.service import ApplicationRunService


class CliRunService:
    def __init__(self, app: ApplicationRunService | None = None) -> None:
        self.app = app or ApplicationRunService()

    def run(
        self,
        task: str,
        workspace: Path,
        *,
        deps: HarnessDependencies | None = None,
        json_output: bool = False,
        **spec_kwargs,
    ) -> tuple[CliResult, str]:
        spec = RunSpec(task=task, workspace=workspace, **spec_kwargs)
        result = self.app.run(spec, deps=deps)
        cli = CliResult.from_run_result(result, run_id=spec.run_id)
        output = format_cli_output(cli, json_mode=json_output)
        return cli, output
