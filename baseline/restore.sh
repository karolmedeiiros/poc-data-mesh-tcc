#!/usr/bin/env bash
#
# Restaura a arquitetura da PoC para o estado congelado em baseline/.
#
# Uso:
#   bash baseline/restore.sh          # pede confirmação
#   bash baseline/restore.sh --force  # sem confirmação
#   bash baseline/restore.sh --dry-run # mostra o que mudaria, sem escrever
#
# O que faz:
#   - Sobrescreve domains/, operational/, platform/, governance/, reports/,
#     odcs_adapter.py, requirements.txt, README.md e .gitignore com a versão do baseline.
#   - Remove arquivos que existem hoje mas não existem no baseline (dentro desses caminhos).
#   - NÃO toca em .git/, .venv/, __pycache__/ nem no próprio baseline/.
#
set -euo pipefail

BASELINE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$BASELINE_DIR/.." && pwd)"

FORCE=0
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --force|-f)  FORCE=1 ;;
    --dry-run|-n) DRY_RUN=1 ;;
    --help|-h)
      sed -n '2,17p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "Argumento desconhecido: $arg" >&2; exit 2 ;;
  esac
done

if [ ! -d "$BASELINE_DIR/domains" ]; then
  echo "ERRO: baseline/ parece incompleto (domains/ não encontrado)." >&2
  exit 1
fi

# ── Integridade do snapshot ────────────────────────────────────────────────
# O baseline é imutável: é o grupo de controle dos experimentos. Se alguém
# sobrescrevê-lo (p.ex. com `rsync ./ baseline/`), as comparações antes/depois
# perdem o sentido — e sem git não há como recuperar. O fingerprint abaixo
# detecta essa situação e avisa antes de restaurar um snapshot adulterado.
# Calculado com caminhos RELATIVOS (cd no subshell) para que o fingerprint não
# dependa de onde o projeto está no disco — mover a pasta não deve invalidá-lo.
#
# Além do agregado (CHECKSUM), gravamos um MANIFEST com o hash de cada arquivo.
# O agregado responde "mudou?"; o manifesto responde "o que mudou?" — sem ele o
# aviso é verdadeiro mas inútil, porque não há como saber qual arquivo foi
# alterado nem se a alteração é semanticamente relevante.
FP_FILTER=(! -name 'CHECKSUM' ! -name 'MANIFEST' ! -path '*/__pycache__/*' ! -name '*.pyc')

baseline_file_hashes() {
  ( cd "$BASELINE_DIR" && find . -type f "${FP_FILTER[@]}" -print0 \
    | sort -z | xargs -0 shasum -a 256 )
}

baseline_fingerprint() {
  baseline_file_hashes | shasum -a 256 | cut -d' ' -f1
}

CHECKSUM_FILE="$BASELINE_DIR/CHECKSUM"
MANIFEST_FILE="$BASELINE_DIR/MANIFEST"
if [ -f "$CHECKSUM_FILE" ] && command -v shasum >/dev/null 2>&1; then
  esperado="$(cat "$CHECKSUM_FILE")"
  atual="$(baseline_fingerprint)"
  if [ "$esperado" != "$atual" ]; then
    echo "⚠️  AVISO: o conteúdo de baseline/ mudou desde que o snapshot foi criado." >&2
    echo "    esperado: $esperado" >&2
    echo "    atual   : $atual" >&2
    echo >&2
    if [ -f "$MANIFEST_FILE" ]; then
      # Um arquivo alterado aparece duas vezes (linha do manifesto e linha
      # atual); um arquivo criado ou removido aparece só de um lado. Reduzimos
      # a uma lista de caminhos com a natureza da divergência.
      divergentes="$(
        diff "$MANIFEST_FILE" <(baseline_file_hashes) \
          | awk '$1=="<" { esperado[$3]=1 } $1==">" { atual[$3]=1 }
                 END {
                   for (p in esperado) print (p in atual ? "alterado" : "removido"), p
                   for (p in atual) if (!(p in esperado)) print "criado  ", p
                 }' | sort -k2 || true
      )"
      if [ -n "$divergentes" ]; then
        echo "    Arquivos divergentes em relação ao MANIFEST:" >&2
        echo "$divergentes" | sed 's/^/      /' >&2
      fi
      echo >&2
    fi
    echo "    O baseline deveria ser IMUTÁVEL. Se ele foi sobrescrito, o estado de" >&2
    echo "    controle do experimento se perdeu e as comparações antes/depois não" >&2
    echo "    são mais confiáveis." >&2
    echo >&2
    if [ "$FORCE" -ne 1 ] && [ "$DRY_RUN" -ne 1 ]; then
      read -r -p "    Restaurar mesmo assim? [y/N] " r
      case "$r" in [yY]|[yY][eE][sS]) ;; *) echo "Cancelado."; exit 1 ;; esac
    fi
  fi
fi

RSYNC_OPTS=(-a --delete
  --exclude='.git/'
  --exclude='.venv/'
  --exclude='__pycache__/'
  --exclude='*.pyc'
  --exclude='baseline/'
  --exclude='BASELINE.md'
  --exclude='restore.sh'
  --exclude='CHECKSUM'
  --exclude='MANIFEST'
  # Resultados dos cenários experimentais e textos do trabalho: preservados
  # entre restaurações. O snapshot restaura a arquitetura, não o material de
  # análise produzido a partir dela.
  --exclude='experimentos/'
  --exclude='docs/'
)

if [ "$DRY_RUN" -eq 1 ]; then
  echo "== DRY RUN — nada será escrito =="
  rsync "${RSYNC_OPTS[@]}" --dry-run --itemize-changes "$BASELINE_DIR/" "$ROOT_DIR/"
  exit 0
fi

if [ "$FORCE" -ne 1 ]; then
  echo "Isto vai SOBRESCREVER o estado atual da arquitetura em:"
  echo "  $ROOT_DIR"
  echo "com o snapshot de baseline/. Alterações não commitadas serão perdidas."
  read -r -p "Continuar? [y/N] " resposta
  case "$resposta" in
    [yY]|[yY][eE][sS]) ;;
    *) echo "Cancelado."; exit 0 ;;
  esac
fi

rsync "${RSYNC_OPTS[@]}" "$BASELINE_DIR/" "$ROOT_DIR/"

# Limpa caches Python que possam referenciar código antigo
find "$ROOT_DIR" -name '__pycache__' -type d -not -path '*/.venv/*' -exec rm -rf {} + 2>/dev/null || true

echo "✓ Arquitetura restaurada a partir de baseline/."
if command -v git >/dev/null 2>&1 && [ -d "$ROOT_DIR/.git" ]; then
  echo
  echo "Diferenças em relação ao último commit:"
  git -C "$ROOT_DIR" status --short
fi
