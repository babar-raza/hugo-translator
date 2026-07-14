---
title: Presentation — Aspose.Slides FOSS for Java API Reference
linktitle: Presentation
description: ドキュメント プロパティを設定
summary: ドキュメント プロパティを設定
categories:
- Class
layout: reference-single
evidence:
  model_sha: 44597f1a09feb16ed1b6f29a1c6b939df4415863
  model_version: 1.0.0
  claims: []
  apis:
  - SaveFormat.PPTX
  - ShapeType.RECTANGLE
  formats:
  - ext: pptx
    support: export
provenance:
  translation_origin: unknown
  source_file: reference.aspose.org/en/slides/java/presentation.md
  source_sha: 78e69894db18b8f46f2de2e5
  last_mechanism: unknown
  auto_updatable: true
  content_hash: 180ed778fc2f4fd890b584c884915390
  content_created_at: '2026-03-27T11:50:48+05:00'

---

BoundingBoxExtent `Presentation` class は PowerPoint の作成、読み込み、保存のためのルートオブジェクトです `.pptx` Aspose.Slides FOSS for Java のファイルです。実装しています `IPresentation`.

**BoundingBoxExtent**: `org.aspose.slides.foss`

```java
import org.aspose.slides.foss.*;

```

```java
public class Presentation implements IPresentation

```

#### BoundingBoxExtent

`IPresentation` -> `Presentation`

---

## BoundingBoxExtent

| BoundingBoxExtent              | BoundingBoxExtent                 |
| ------------------------------ | --------------------------------- |
| `Presentation()`               | 1枚のスライドがある新しい空白のプレゼンテーションを作成します。. |
| `Presentation(String path)`    | 指定されたファイルパスからプレゼンテーションを開きます。.     |
| `Presentation(InputStream in)` | 指定された入力ストリームからプレゼンテーションを開きます。.    |

**BoundingBoxExtent**:

```java
import org.aspose.slides.foss.*;

// Create a new empty presentation
Presentation prs = new Presentation();

// Open an existing PPTX file
Presentation prs2 = new Presentation("deck.pptx");

// Load from a stream
InputStream stream = new FileInputStream("deck.pptx");
Presentation prs3 = new Presentation(stream);

```

---

## BoundingBoxExtent

| BoundingBoxExtent                                            | BoundingBoxExtent              | BoundingBoxExtent | BoundingBoxExtent                   |
| ------------------------------------------------------------ | ------------------------------ | ----------------- | ----------------------------------- |
| `getSlides()`                                                | `ISlideCollection`             | BoundingBoxExtent | プレゼンテーション内のスライドの順序付けられたコレクション。.     |
| `getMasters()`                                               | `IMasterSlideCollection`       | BoundingBoxExtent | マスタースライドのコレクション。.                   |
| `getLayoutSlides()`                                          | `IGlobalLayoutSlideCollection` | BoundingBoxExtent | すべてのマスターにまたがるすべてのレイアウトスライドのコレクション。. |
| `getCommentAuthors()`                                        | `ICommentAuthorCollection`     | BoundingBoxExtent | コメント作者のコレクション。.                     |
| `getDocumentProperties()`                                    | `IDocumentProperties`          | BoundingBoxExtent | コア、アプリケーション、およびカスタムドキュメントメタデータ。.    |
| `getImages()`                                                | `IImageCollection`             | BoundingBoxExtent | プレゼンテーションに埋め込まれたすべての画像のコレクション。.     |
| `getNotesSize()`                                             | `INotesSize`                   | BoundingBoxExtent | ノートスライドのサイズ設定。.                     |
| `getSourceFormat()`                                          | `SourceFormat`                 | BoundingBoxExtent | 読み込まれたプレゼンテーションソースの形式。.             |
| `getCurrentDateTime()` / `setCurrentDateTime(LocalDateTime)` | `LocalDateTime`                | 読み取り/書き込み         | 日付・時刻プレースホルダーに使用される日時。.             |
| `getFirstSlideNumber()` / `setFirstSlideNumber(int)`         | `int`                          | 読み取り/書き込み         | プレゼンテーション内の最初のスライド番号。.              |

---

## BoundingBoxExtent

### save(String path)

プレゼンテーションをファイルに保存します（デフォルトは PPTX 形式）。.

| BoundingBoxExtent | BoundingBoxExtent | BoundingBoxExtent |
| ----------------- | ----------------- | ----------------- |
| `path`            | `String`          | 宛先ファイルパス。.        |

```java
prs.save("output.pptx");

```

### save(OutputStream stream)

プレゼンテーションを出力ストリームに保存します。.

| BoundingBoxExtent | BoundingBoxExtent | BoundingBoxExtent |
| ----------------- | ----------------- | ----------------- |
| `stream`          | `OutputStream`    | 宛先ストリーム。.         |

### save(String path, SaveFormat format)

指定された形式でプレゼンテーションをファイルに保存します。.

| BoundingBoxExtent | BoundingBoxExtent | BoundingBoxExtent             |
| ----------------- | ----------------- | ----------------------------- |
| `path`            | `String`          | 宛先ファイルパス。.                    |
| `format`          | `SaveFormat`      | 出力形式（例：., `SaveFormat.PPTX`). |

```java
prs.save("output.pptx", SaveFormat.PPTX);

```

### save(OutputStream stream, SaveFormat format)

指定された形式でプレゼンテーションをストリームに保存します。.

### save(String path, SaveFormat format, ISaveOptions options)

追加オプションを使用してプレゼンテーションをファイルに保存します。.

| BoundingBoxExtent | BoundingBoxExtent | BoundingBoxExtent  |
| ----------------- | ----------------- | ------------------ |
| `path`            | `String`          | 宛先ファイルパス。.         |
| `format`          | `SaveFormat`      | 出力形式。.             |
| `options`         | `ISaveOptions`    | 出力動作を制御する保存オプション。. |

---

## 使用例

### シェイプでプレゼンテーションを作成する

```java
import org.aspose.slides.foss.*;

Presentation prs = new Presentation();
ISlide slide = prs.getSlides().get(0);
IAutoShape shape = slide.getShapes().addAutoShape(
    ShapeType.RECTANGLE, 50, 50, 300, 100);
shape.addTextFrame("Hello, Slides!");
prs.save("hello.pptx", SaveFormat.PPTX);

```

### 開く、検査する、再保存する

```java
import org.aspose.slides.foss.*;

Presentation prs = new Presentation("existing.pptx");
System.out.println("Slides: " + prs.getSlides().size());
for (int i = 0; i < prs.getSlides().size(); i++) {
    ISlide slide = prs.getSlides().get(i);
    System.out.println("  Slide " + i + ": " + slide.getShapes().size() + " shapes");
}
prs.save("existing-updated.pptx", SaveFormat.PPTX);

```

### ドキュメント プロパティを設定

```java
import org.aspose.slides.foss.*;

Presentation prs = new Presentation();
prs.getDocumentProperties().setTitle("Q1 Results");
prs.getDocumentProperties().setAuthor("Finance Team");
prs.getDocumentProperties().setSubject("Quarterly Review");
prs.save("q1.pptx", SaveFormat.PPTX);

```

---

## 参照

- [Slides Java API リファレンス ホーム](https://reference.aspose.org/slides/java/)
- [BoundingBoxExtent](https://reference.aspose.org/slides/java/Slide/)
- [SlideCollection](https://reference.aspose.org/slides/java/SlideCollection/)
- [BoundingBoxExtent](https://reference.aspose.org/slides/java/Shape/)
- [TextFrame](https://reference.aspose.org/slides/java/TextFrame/)

