---
linkTitle: Presentation
title: Presentation
description: "`Presentation`クラス (30の方法と11つの性質を持つIPresentationを継承)"
summary: "`Presentation`クラス (30の方法と11つの性質を持つIPresentationを継承)"
categories:
  - Class
layout: reference-single
provenance:
    content_origin: skill-generated
    last_mechanism: skill
    auto_updatable: true
    content_created_at: '2026-05-01T09:22:48+00:00'
    content_hash: 9776c90718acc280dce87ceaf8b15d8e
evidence:
    model_sha: 44597f1a09feb16ed1b6f29a1c6b939df4415863
    model_version: 1.0.0
    claims: []
    apis:
      - Presentation
      - Presentation.Presentation
      - Presentation.asIPresentationComponent
      - Presentation.close
      - Presentation.currentDateTime
      - Presentation.dispose
      - Presentation.getCommentAuthors
      - Presentation.getCurrentDateTime
      - Presentation.getDocumentProperties
      - Presentation.getFirstSlideNumber
      - Presentation.getImages
      - Presentation.getLayoutSlides
      - Presentation.getMasters
      - Presentation.getNotesSize
      - Presentation.getPresentation
      - Presentation.getSlides
      - Presentation.getSourceFormat
      - Presentation.presentation
      - Presentation.save
      - Presentation.setCurrentDateTime
      - Presentation.setFirstSlideNumber
grade: A
graded_content_hash: "9776c90718acc280dce87ceaf8b15d8e"
grade_reasons:
  - "2 WARN finding(s) [audit] -> base grade A"
---

## 概要

`Presentation` クラスです. これは,JavaのPLACEHOLDER_0で使用されます. 遺産は: `IPresentation`.

PowerPoint プレゼンテーションを表します.

このクラスでは,Java プログラムでプレゼンテーションオブジェクトと作業するための 30 つの方法が提供されています. 可能な方法には: `Presentation`, `asIPresentationComponent`, `close`, `dispose`, `getCommentAuthors`, `getCurrentDateTime`, `getDocumentProperties`, `getFirstSlideNumber`, `getImages`, `getLayoutSlides`, `getMasters`, `getNotesSize`,追加方法6つ. すべてのパブリックメンバーは,JavaのパッケージのためのFOSS Aspose.Slides をインストールした後で,任意の Java アプリケーションにアクセスできます. 特性: `commentAuthors`, `currentDateTime`, `documentProperties`, `firstSlideNumber`, `images`, `layoutSlides`,そして5つ以上.

## 特性について

| 名称 (名)               | タイプ                            | Access | 記述                |
| -------------------- | ------------------------------ | ------ | ----------------- |
| `presentation`       | `IPresentation`                | 読み取ること | プレゼンテーションをします.    |
| `currentDateTime`    | `LocalDateTime`                | 読み取ること | 元の日付の時間です.        |
| `documentProperties` | `IDocumentProperties`          | 読み取ること | 文書のプロパティを入手します.   |
| `commentAuthors`     | `ICommentAuthorCollection`     | 読み取ること | コメントの作者も取ります.     |
| `slides`             | `ISlideCollection`             | 読み取ること | スライドを手に入れる.       |
| `notesSize`          | `INotesSize`                   | 読み取ること | 音の大きさを把握します.      |
| `layoutSlides`       | `IGlobalLayoutSlideCollection` | 読み取ること | レイアウトのスライドを手に入れる. |
| `masters`            | `IMasterSlideCollection`       | 読み取ること | マスターを手に入れる.       |
| `images`             | `IImageCollection`             | 読み取ること | 画像を撮るんだ.          |
| `sourceFormat`       | `SourceFormat`                 | 読み取ること | ソースのフォーマットを取得します. |
| `firstSlideNumber`   | `int`                          | 読み取ること | グラフの番号を入力します.     |

## 方法について

| Signature                                                                              | 記述                                        |
| -------------------------------------------------------------------------------------- | ----------------------------------------- |
| `Presentation()`                                                                       | 画面を1つのスライドで表示する.                          |
| `Presentation(path: String)`                                                           | 指定されたファイルパスのプレゼンテーションを開きます.               |
| `Presentation(in: InputStream)`                                                        | 与えられた入力ストリームからプレゼンテーションを開きます.             |
| `save(path: String)`                                                                   | 選択したフォーマットでストリームに表示されたスライドインデックスのみを保存する.  |
| `save(stream: OutputStream)`                                                           |                                           |
| `getPresentation()` → `IPresentation`                                                  | プレゼンテーションを返します.                           |
| `getCurrentDateTime()` → `LocalDateTime`                                               | 元の日付を表示する.                                |
| `setCurrentDateTime(value: LocalDateTime)`                                             | 現在の日付時値を設定する.                             |
| `getDocumentProperties()` → `IDocumentProperties`                                      | ファイルのプロパティを返します.                          |
| `getCommentAuthors()` → `ICommentAuthorCollection`                                     | コメントの作成者返信します.                            |
| `getSlides()` → `ISlideCollection`                                                     | グラフを返します.                                 |
| `getNotesSize()` → `INotesSize`                                                        | 音符のサイズを返します.                              |
| `getLayoutSlides()` → `IGlobalLayoutSlideCollection`                                   | レイアウトスライドを返します.                           |
| `getMasters()` → `IMasterSlideCollection`                                              | マスターを返します.                                |
| `getImages()` → `IImageCollection`                                                     | 画像を返します.                                  |
| `getSourceFormat()` → `SourceFormat`                                                   | ソースフォーマットを返します.                           |
| `getFirstSlideNumber()` → `int`                                                        | グラフの番号を返します.                              |
| `setFirstSlideNumber(value: int)`                                                      | グラフの値が設定されます.                             |
| `asIPresentationComponent()` → `IPresentationComponent`                                | プレゼテーションを IPresentationComponent として返します. |
| `save(path: String, format: SaveFormat)`                                               |                                           |
| `save(stream: OutputStream, format: SaveFormat)`                                       |                                           |
| `save(path: String, format: SaveFormat, options: ISaveOptions)`                        |                                           |
| `save(stream: OutputStream, format: SaveFormat, options: ISaveOptions)`                |                                           |
| `save(path: String, slides: int[], format: SaveFormat)`                                |                                           |
| `save(path: String, slides: int[], format: SaveFormat, options: ISaveOptions)`         |                                           |
| `save(stream: OutputStream, slides: int[], format: SaveFormat)`                        |                                           |
| `save(stream: OutputStream, slides: int[], format: SaveFormat, options: ISaveOptions)` |                                           |
| `save(options: ISaveOptions)`                                                          | **FOSS版では実装されていません. は実行時に投げられます.**        |
| `dispose()`                                                                            | プレゼンテーションで使用されるすべてのリソースを公開する.             |
| `close()`                                                                              | プレゼンテーションを閉じてリソースを公開する                    |

## 参照する

- [Aspose.Slides — Enterprise API Reference](https://reference.aspose.com/slides/)

