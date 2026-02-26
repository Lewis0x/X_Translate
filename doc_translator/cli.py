from __future__ import annotations

import argparse
from pathlib import Path
from typing import List
from typing import Tuple
from pathlib import Path

from doc_translator.comparison import collect_sample_texts
from doc_translator.comparison import choose_best_profile
from doc_translator.config import load_local_config
from doc_translator.config import is_pid_alive
from doc_translator.config import read_lock
from doc_translator.config import read_profiles
from doc_translator.config import write_lock
from doc_translator.glossary import Glossary
from doc_translator.pipeline import TranslationPipeline
from doc_translator.reporting import RunReport, build_logger
from doc_translator.translator import TranslationConfig, create_translator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="文档翻译工具（docx/xlsx/pdf）")
    parser.add_argument("--input", nargs="+", required=True, help="输入文件或目录，可传多个")
    parser.add_argument("--target", required=True, help="目标语言代码，如 en")
    parser.add_argument("--source", default="zh", help="源语言代码，默认 zh")
    parser.add_argument("--glossary", default=None, help="术语表路径（csv/json）")
    parser.add_argument("--output-dir", default="./output", help="输出目录（建议新目录）")
    parser.add_argument("--suffix", default=None, help="输出文件后缀，默认与target一致")
    parser.add_argument("--batch-size", type=int, default=20, help="单次翻译批大小")
    parser.add_argument("--max-retries", type=int, default=3, help="失败重试次数")
    parser.add_argument("--rate-limit-rpm", type=int, default=60, help="每分钟请求数")
    parser.add_argument("--provider", default="openai", help="模型提供商：openai 或 openai_compatible")
    parser.add_argument("--model", default="", help="模型名称，未传则从配置或环境变量读取")
    parser.add_argument("--base-url", default="", help="API Base URL（兼容接口场景必填）")
    parser.add_argument("--endpoint", default="/chat/completions", help="兼容接口 endpoint，默认 /chat/completions")
    parser.add_argument("--api-key", default="", help="API Key（优先级高于本地配置）")
    parser.add_argument("--config", default="./local.config.json", help="本地配置文件路径")
    parser.add_argument("--compare-apis", action="store_true", help="启用多模型对比后自动选择最佳模型")
    parser.add_argument("--compare-models", default="", help="用于对比的模型列表（逗号分隔）")
    parser.add_argument("--compare-sample-size", type=int, default=80, help="模型对比采样段落数")
    parser.add_argument("--compare-report", default="compare_report.json", help="模型对比报告文件名")
    parser.add_argument("--force-run", action="store_true", help="忽略运行锁并强制执行")
    return parser


def main() -> None:
    args = build_parser().parse_args()

    output_dir = Path(args.output_dir).resolve()
    suffix = args.suffix or args.target
    logger = build_logger(output_dir / "logs" / "translator.log")
    local_config = load_local_config(args.config)

    lock_file = output_dir / ".run.lock"
    _acquire_run_lock(lock_file=lock_file, owner="doc_translator", force_run=args.force_run)

    try:
        glossary = Glossary.load(args.glossary)
        files = TranslationPipeline(
            translator=create_translator(
                _make_config_from_args(
                    args=args,
                    local_config=local_config,
                    provider_override=None,
                    model_override=None,
                    profile_overrides=None,
                )
            ),
            glossary=glossary,
        ).collect_files(args.input)
        if not files:
            logger.warning("未找到可处理文件，请检查输入路径")
            return

        if args.compare_apis:
            profile_candidates = _build_compare_profiles(args=args, local_config=local_config)
            if len(profile_candidates) < 2:
                logger.warning("可对比模型少于2个，自动退化为单模型运行")
                active_name, active_config = _single_profile(args=args, local_config=local_config)
            else:
                sample_texts = collect_sample_texts(files, sample_size=max(10, args.compare_sample_size))
                if not sample_texts:
                    logger.warning("无法抽取采样文本，自动退化为单模型运行")
                    active_name, active_config = _single_profile(args=args, local_config=local_config)
                else:
                    best_name, best_config, _results = choose_best_profile(
                        profiles=profile_candidates,
                        sample_texts=sample_texts,
                        logger=logger,
                        compare_report_file=output_dir / args.compare_report,
                    )
                    logger.info("对比完成，选择最佳模型: %s (%s/%s)", best_name, best_config.provider, best_config.model)
                    active_name, active_config = best_name, best_config
        else:
            active_name, active_config = _single_profile(args=args, local_config=local_config)

        translator = create_translator(active_config)
        pipeline = TranslationPipeline(translator=translator, glossary=glossary)
        report = RunReport(
            source_lang=args.source,
            target_lang=args.target,
            model=f"{active_name}:{active_config.model}",
        )
        pipeline.process_files(files, output_dir, suffix, report, logger)
        report_file = output_dir / "report.json"
        report.write(report_file)
        logger.info("处理结束，报告已生成: %s", report_file)
    finally:
        _release_run_lock(lock_file)


def _build_compare_profiles(args, local_config: dict) -> List[Tuple[str, TranslationConfig]]:
    profiles: List[Tuple[str, TranslationConfig]] = []
    seen: set[str] = set()

    single_name, single_config = _single_profile(args=args, local_config=local_config)
    profiles.append((single_name, single_config))
    seen.add(single_name)

    for model in [item.strip() for item in args.compare_models.split(",") if item.strip()]:
        name = f"model:{model}"
        if name in seen:
            continue
        profiles.append(
            (
                name,
                _make_config_from_args(
                    args=args,
                    local_config=local_config,
                    provider_override=None,
                    model_override=model,
                    profile_overrides=None,
                ),
            )
        )
        seen.add(name)

    for profile in read_profiles(local_config):
        name = str(profile.get("name") or profile.get("model") or "profile")
        if name in seen:
            continue
        profiles.append(
            (
                name,
                _make_config_from_args(
                    args=args,
                    local_config=local_config,
                    provider_override=str(profile.get("provider", "")).strip() or None,
                    model_override=str(profile.get("model", "")).strip() or None,
                    profile_overrides=profile,
                ),
            )
        )
        seen.add(name)
    return profiles


def _single_profile(args, local_config: dict) -> Tuple[str, TranslationConfig]:
    config = _make_config_from_args(
        args=args,
        local_config=local_config,
        provider_override=None,
        model_override=None,
        profile_overrides=None,
    )
    name = f"default:{config.provider}:{config.model}"
    return name, config


def _make_config_from_args(
    args,
    local_config: dict,
    provider_override: str | None,
    model_override: str | None,
    profile_overrides: dict | None,
) -> TranslationConfig:
    profile_overrides = profile_overrides or {}
    provider = provider_override or args.provider or str(local_config.get("LLM_PROVIDER", "openai"))
    provider_lower = provider.strip().lower()

    cli_base_url = args.base_url if provider_override is None and not profile_overrides else ""
    cli_endpoint = args.endpoint if provider_override is None and not profile_overrides else ""
    cli_api_key = args.api_key if provider_override is None and not profile_overrides else ""
    cli_model = model_override or (args.model if provider_override is None and not profile_overrides else "")

    profile_base_url = str(profile_overrides.get("base_url", "")).strip()
    profile_endpoint = str(profile_overrides.get("endpoint", "")).strip()
    profile_api_key = str(profile_overrides.get("api_key", "")).strip()
    profile_model = str(profile_overrides.get("model", "")).strip()
    profile_provider = str(profile_overrides.get("provider", "")).strip()
    if profile_provider:
        provider = profile_provider
        provider_lower = provider.strip().lower()

    if provider_lower == "openai":
        resolved_base_url = (
            cli_base_url
            or profile_base_url
            or str(local_config.get("OPENAI_BASE_URL", ""))
            or str(local_config.get("LLM_BASE_URL", ""))
        )
        resolved_endpoint = (
            cli_endpoint
            or profile_endpoint
            or str(local_config.get("OPENAI_ENDPOINT", ""))
            or str(local_config.get("LLM_ENDPOINT", "/chat/completions"))
        )
    else:
        resolved_base_url = cli_base_url or profile_base_url or str(local_config.get("LLM_BASE_URL", ""))
        resolved_endpoint = (
            cli_endpoint
            or profile_endpoint
            or str(local_config.get("LLM_ENDPOINT", "/chat/completions"))
        )

    resolved_api_key = cli_api_key or profile_api_key or str(local_config.get("OPEN_API_KEY", ""))
    resolved_model = cli_model or profile_model or str(local_config.get("LLM_MODEL", local_config.get("OPENAI_MODEL", "")))

    return TranslationConfig(
        source_lang=args.source,
        target_lang=args.target,
        provider=provider,
        api_key=resolved_api_key,
        model=resolved_model,
        base_url=resolved_base_url,
        endpoint=resolved_endpoint,
        batch_size=int(profile_overrides.get("batch_size", args.batch_size)),
        max_retries=int(profile_overrides.get("max_retries", args.max_retries)),
        rate_limit_rpm=int(profile_overrides.get("rate_limit_rpm", args.rate_limit_rpm)),
    )


def _acquire_run_lock(lock_file: Path, owner: str, force_run: bool) -> None:
    if not lock_file.exists():
        write_lock(lock_file, owner=owner)
        return
    lock_info = read_lock(lock_file)
    pid = int(lock_info.get("pid", 0) or 0)
    if is_pid_alive(pid) and not force_run:
        raise RuntimeError(f"检测到运行中的任务锁: {lock_file} (pid={pid})，如需强制执行请加 --force-run")
    write_lock(lock_file, owner=owner)


def _release_run_lock(lock_file: Path) -> None:
    if lock_file.exists():
        lock_file.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
