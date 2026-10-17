//! dwgconv — conversor DWG <-> DXF do LeafDraw, sobre a acadrust (MPL-2.0).
//!
//! Uso: dwgconv ENTRADA SAIDA [--as R2000|R2004|R2010|R2013|R2018] [--failsafe]
//!
//! O formato de cada lado vem da extensão (.dwg ou .dxf). `--as` escolhe a versão
//! gravada (padrão: a do arquivo lido); `--failsafe` recupera o que der de DWG com
//! objetos que a acadrust não entende, em vez de abortar.
use std::path::Path;
use std::process::ExitCode;

use acadrust::types::DxfVersion;
use acadrust::{DwgReadOptions, DwgReader, DwgWriter, DxfReader, DxfWriter};

fn ext(p: &str) -> String {
    Path::new(p).extension().and_then(|e| e.to_str()).unwrap_or("").to_ascii_lowercase()
}

fn version(name: &str) -> Option<DxfVersion> {
    Some(match name.to_ascii_uppercase().as_str() {
        "AC1015" | "R2000" => DxfVersion::AC1015,
        "AC1018" | "R2004" => DxfVersion::AC1018,
        "AC1024" | "R2010" => DxfVersion::AC1024,
        "AC1027" | "R2013" => DxfVersion::AC1027,
        "AC1032" | "R2018" => DxfVersion::AC1032,
        _ => return None,
    })
}

fn run(args: &[String]) -> Result<(), String> {
    if args.iter().any(|a| a == "--version") {
        println!("dwgconv {} (acadrust 0.6.4)", env!("CARGO_PKG_VERSION"));
        return Ok(());
    }
    let mut files: Vec<&str> = Vec::new();
    let mut as_version = None;
    let mut failsafe = false;
    let mut it = args.iter();
    while let Some(a) = it.next() {
        match a.as_str() {
            "--as" => {
                let v = it.next().ok_or("--as sem versão")?;
                as_version = Some(version(v).ok_or_else(|| format!("versão inválida: {v}"))?);
            }
            "--failsafe" => failsafe = true,
            _ => files.push(a),
        }
    }
    let [input, output] = files[..] else {
        return Err("uso: dwgconv ENTRADA SAIDA [--as R2018] [--failsafe]".into());
    };
    let mut doc = match ext(input).as_str() {
        "dwg" => {
            let opts = if failsafe { DwgReadOptions::failsafe() } else { DwgReadOptions::default() };
            DwgReader::from_file_with_options(input, opts).and_then(|mut r| r.read())
        }
        "dxf" => DxfReader::from_file(input).and_then(|r| r.read()),
        e => return Err(format!("extensão de entrada não suportada: .{e}")),
    }
    .map_err(|e| format!("leitura de {input}: {e}"))?;
    if let Some(v) = as_version {
        doc.version = v;
    }
    match ext(output).as_str() {
        "dwg" => DwgWriter::write_to_file(output, &doc),
        "dxf" => DxfWriter::new(&doc).write_to_file(output),
        e => return Err(format!("extensão de saída não suportada: .{e}")),
    }
    .map_err(|e| format!("gravação de {output}: {e}"))
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match run(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("erro: {e}");
            ExitCode::FAILURE
        }
    }
}
