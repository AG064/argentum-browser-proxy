# Argentum Browser PKG - Инструкция по сборке

## Что нужно

1. **Windows 10/11** (можно в виртуалке)
2. **PS4 Fake PKG Tools 3.87** - скачать с GitHub:
   https://github.com/CyB1K/PS4-Fake-PKG-Tools-3.87

## Шаг 1: Скачай инструменты

1. Скачай архив `PS4-Fake-PKG-Tools-3.87.zip` с GitHub
2. Распакуй в `C:\PS4Tools\`

## Шаг 2: Скачай Argentum Browser

1. Скачай файл браузера с сервера:
   ```
   http://192.168.0.238:8765/argentum_browser.html
   ```
2. Сохрани как `C:\PS4Tools\content\argentum_browser.html`

## Шаг 3: Создай GP4 проект

1. Открой `orbis-pub-gen.exe` из папки `C:\PS4Tools\`
2. File → New Project
3. Заполни:
   - **Title**: Argentum Browser
   - **Content ID**: ARGB0000100 (любой уникальный)
   - **Category**: PS4 System Software
   - **Version**: 01.00
4. Добавь файл:
   - Правая кнопка на "Content" → Add Files
   - Выбери `argentum_browser.html`
5. Пропиши путь к файлу в поле "URL" или оставь пустым для редиректа

## Шаг 4: Создай PARAM.SFO

1. В `orbis-pub-gen.exe`:
   - Project → Generate PARAM.SFO
   - Или запусти `orbis-pub-sfo.exe`

## Шаг 5: Собери PKG

1. В `orbis-pub-gen.exe`:
   - Command → Build PKG
   - Или запусти `orbis-pub-cmd.exe`

Или через командную строку:
```cmd
cd C:\PS4Tools
orbis-pub-cmd.exe --build "C:\PS4Tools\project.gp4" --output "C:\PS4Tools\argentum_browser.pkg"
```

## Шаг 6: Установи на PS4

1. Скопируй `argentum_browser.pkg` на PS4 через FTP
2. Установи через Goldhen → Package Installer
   (или через FPKGi если установлен)

## Альтернатива: Без PKG

Просто открой на PS4 браузер и зайди на:
```
http://192.168.0.238:8765/browser
```
Потом Add to Home Screen - будет как приложение.

## Файлы

- Браузер: `http://192.168.0.238:8765/browser`
- Статический UI: `http://192.168.0.238:8765/argentum_browser.html`
- Прокси: `http://192.168.0.238:8765/`
