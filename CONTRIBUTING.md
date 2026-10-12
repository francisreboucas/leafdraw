# Como contribuir

Obrigado pelo interesse no LeafDraw! Contribuições são bem-vindas: relatos de bugs, sugestões,
documentação e código.

Ao participar, você concorda em seguir o nosso [Código de Conduta](CODE_OF_CONDUCT.md).

## Relatar bugs e sugerir melhorias

- Antes de abrir uma issue, procure nas [issues existentes](https://github.com/francisreboucas/leafdraw/issues)
  se o assunto já foi tratado.
- Use os modelos de issue: **Relatar bug** ou **Sugerir funcionalidade**.
- Para bugs, informe a versão do LeafDraw, a versão do Windows e a placa de vídeo, e descreva os
  passos para reproduzir. Se possível, anexe um arquivo `.leaf` mínimo que mostre o problema.
- Vulnerabilidades de segurança **não** devem ser relatadas em issues públicas; veja
  [SECURITY.md](SECURITY.md).

## Preparar o ambiente

Requer Python 3 (veja a versão mínima em `pyproject.toml`) e placa de vídeo com OpenGL 3.3.

```powershell
git clone https://github.com/francisreboucas/leafdraw.git
cd leafdraw
python -m venv .venv
.venv\Scripts\python -m pip install -e .[dev]
.venv\Scripts\python -m leafdraw            # executa o aplicativo
.venv\Scripts\python -m pytest              # roda os testes
```

## Enviar alterações (pull requests)

1. Faça um fork do repositório e crie um branch a partir de `main`
   (por exemplo, `corrige-cota-arco` ou `nova-ferramenta-muro`).
2. Mantenha cada pull request focado em uma única mudança.
3. Escreva o código no mesmo estilo do código ao redor e adicione ou atualize testes em `tests/`
   quando a mudança afetar o núcleo (`leafdraw/core`).
4. Rode `python -m pytest` e confirme que todos os testes passam.
5. Textos da interface ficam em português do Brasil.
6. Escreva mensagens de commit em português, no imperativo e descrevendo o que muda
   (por exemplo, "Corrige o arredondamento das cotas de arco").
7. Abra o pull request preenchendo o modelo e referencie a issue relacionada, se houver
   (`Closes #123`).

## Licença

O LeafDraw é distribuído sob a [GPL-3.0](LICENSE). Ao enviar uma contribuição, você concorda que
ela seja licenciada nos mesmos termos.
