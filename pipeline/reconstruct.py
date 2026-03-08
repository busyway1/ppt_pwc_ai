#!/usr/bin/env python3
"""
HTML 슬라이드를 html2pptx.js를 통해 PPTX로 변환한다.

Usage:
    python pipeline/reconstruct.py slide.html output.pptx
"""

import argparse
import re
import subprocess
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNNER_SCRIPT = PROJECT_ROOT / "tools" / "html2pptx_runner.js"


def _ensure_runner_script() -> Path:
    """html2pptx_runner.js가 없으면 생성한다."""
    if RUNNER_SCRIPT.exists():
        return RUNNER_SCRIPT

    runner_code = """\
#!/usr/bin/env node
/**
 * html2pptx wrapper - CLI에서 HTML을 PPTX로 변환한다.
 *
 * Usage: node tools/html2pptx_runner.js <html_file> <output_pptx> [width_inches] [height_inches]
 *   width/height: custom slide dimensions in inches (default: 13.33 x 7.5)
 */

const path = require('path');
const pptxgen = require('pptxgenjs');
const html2pptx = require('./html2pptx.js');

async function main() {
  const args = process.argv.slice(2);
  if (args.length < 2) {
    console.error('Usage: node html2pptx_runner.js <html_file> <output_pptx> [width] [height]');
    process.exit(1);
  }

  const htmlFile = path.resolve(args[0]);
  const outputPath = path.resolve(args[1]);
  const widthInches = parseFloat(args[2]) || 13.33;
  const heightInches = parseFloat(args[3]) || 7.5;

  const pres = new pptxgen();
  // Use defineLayout for custom dimensions matching the HTML body
  pres.defineLayout({ name: 'CUSTOM', width: widthInches, height: heightInches });
  pres.layout = 'CUSTOM';

  try {
    await html2pptx(htmlFile, pres);
    await pres.writeFile({ fileName: outputPath });
    console.log(JSON.stringify({ success: true, output: outputPath }));
  } catch (err) {
    console.error(JSON.stringify({ success: false, error: err.message }));
    process.exit(1);
  }
}

main();
"""
    RUNNER_SCRIPT.write_text(runner_code, encoding="utf-8")
    return RUNNER_SCRIPT


def _fix_korean_fonts(pptx_path: Path, font_family: str = "맑은 고딕") -> None:
    """PPTX 내부 XML에서 한국어 폰트 참조를 교정한다.

    pptxgenjs가 생성한 PPTX에서 한국어 폰트가 올바르게 설정되지 않을 수 있다.
    XML 내의 <a:latin> 및 <a:ea> 태그의 typeface를 검사하고 수정한다.
    """
    pptx_path_str = str(pptx_path)
    modified = False

    with zipfile.ZipFile(pptx_path_str, "r") as zin:
        file_list = zin.namelist()
        contents = {}
        for name in file_list:
            data = zin.read(name)
            if name.startswith("ppt/slides/") and name.endswith(".xml"):
                text = data.decode("utf-8")
                # <a:ea> 태그에 올바른 폰트 설정
                new_text = re.sub(
                    r'(<a:ea\s+typeface=")([^"]*?)(")',
                    rf"\1{font_family}\3",
                    text,
                )
                # <a:ea> 태그가 없지만 <a:latin>이 있는 경우 추가
                if "<a:ea" not in new_text and "<a:latin" in new_text:
                    new_text = new_text.replace(
                        "</a:latin>",
                        f'</a:latin><a:ea typeface="{font_family}"/>',
                    )
                if new_text != text:
                    modified = True
                    data = new_text.encode("utf-8")
            contents[name] = data

    if modified:
        with zipfile.ZipFile(pptx_path_str, "w", zipfile.ZIP_DEFLATED) as zout:
            for name in file_list:
                zout.writestr(name, contents[name])


def reconstruct_slide(
    html_path: str | Path,
    output_pptx_path: str | Path,
    slide_width: float = 13.33,
    slide_height: float = 7.5,
    font_family: str = "맑은 고딕",
) -> Path:
    """HTML 파일을 PPTX로 변환한다.

    Args:
        html_path: 입력 HTML 파일 경로.
        output_pptx_path: 출력 PPTX 파일 경로.
        slide_width: 슬라이드 너비 (인치).
        slide_height: 슬라이드 높이 (인치).
        font_family: 한국어 폰트 이름.

    Returns:
        생성된 PPTX 파일의 Path.

    Raises:
        RuntimeError: Node.js 실행 실패 시.
    """
    html_path = Path(html_path).resolve()
    output_pptx_path = Path(output_pptx_path).resolve()
    output_pptx_path.parent.mkdir(parents=True, exist_ok=True)

    if not html_path.exists():
        raise FileNotFoundError(f"HTML file not found: {html_path}")

    runner = _ensure_runner_script()

    result = subprocess.run(
        [
            "node",
            str(runner),
            str(html_path),
            str(output_pptx_path),
            str(slide_width),
            str(slide_height),
        ],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=120,
    )

    if result.returncode != 0:
        error_msg = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"html2pptx failed: {error_msg}")

    # 한국어 폰트 후처리
    if output_pptx_path.exists():
        _fix_korean_fonts(output_pptx_path, font_family)

    return output_pptx_path


def main():
    parser = argparse.ArgumentParser(
        description="HTML 슬라이드를 PPTX로 변환한다.",
    )
    parser.add_argument("html_file", help="입력 HTML 파일 경로")
    parser.add_argument("output_pptx", help="출력 PPTX 파일 경로")
    parser.add_argument(
        "--width", type=float, default=13.33, help="슬라이드 너비 (인치)"
    )
    parser.add_argument(
        "--height", type=float, default=7.5, help="슬라이드 높이 (인치)"
    )
    parser.add_argument("--font", default="맑은 고딕", help="한국어 폰트 이름")

    args = parser.parse_args()

    try:
        output = reconstruct_slide(
            args.html_file, args.output_pptx, args.width, args.height, args.font
        )
        print(f"Created PPTX: {output}")
    except (FileNotFoundError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
