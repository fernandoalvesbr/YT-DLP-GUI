# YT-DLP GUI

Interface gráfica em Python para o [yt-dlp](https://github.com/yt-dlp/yt-dlp), feita com Tkinter.

## Recursos

- Download de vídeo ou somente áudio
- Qualidade de vídeo de 360p até 4K
- Conversão para MP3, M4A, Opus, WAV ou FLAC
- Download de playlists
- Progresso, velocidade e tempo restante
- Cancelamento de download
- Legendas em português e inglês
- Miniaturas e metadados
- Cookies do Chrome, Edge, Firefox, Opera, Brave, Vivaldi ou Safari
- Seleção da pasta de destino
- Compatível com Windows, Linux e macOS

## Instalação

É recomendado usar Python 3.10 ou mais recente.

```bash
python -m pip install -U yt-dlp
```

Para todas as funções de áudio, junção de vídeo e incorporação de metadados, instale também o FFmpeg.

### Windows

Uma opção simples é instalar com Winget:

```powershell
winget install Gyan.FFmpeg
```

Feche e abra novamente o terminal após instalar.

### Debian/Ubuntu

```bash
sudo apt update
sudo apt install python3-tk ffmpeg
```

## Execução

```bash
python yt_dlp_gui.py
```

## Gerar um EXE no Windows

```powershell
python -m pip install -U pyinstaller yt-dlp
pyinstaller --noconfirm --onefile --windowed --name YT-DLP-GUI --collect-all yt_dlp yt_dlp_gui.py
```

O executável será criado na pasta `dist`.

> Observação: o FFmpeg ainda deve estar instalado no sistema ou ser colocado no PATH.

## Uso responsável

Use o programa somente para conteúdo que você tenha permissão para baixar. O usuário é responsável por respeitar direitos autorais, termos de serviço e leis aplicáveis.
