---
author: Muzammil Khan
categories:
- Aspose.BarCode Plugin Family
date: 2024-11-09
description: Gérer et afficher des images de code bar dans ASP.NET MVC en utilisant l'Aspose.BarCode pour l'API .NET. Ce puissant plugin .NET pour la génération de code bar est disponible pour seulement $99.
draft: false
lastmod: '2025-04-08'
seoTitle: Generate and Display Barcode Image in ASP.NET MVC
summary: En tant que développeur .NET, vous pouvez facilement générer différents types de codes bar et les afficher dans les pages Razor en utilisant le plug-in Aspose. Ce guide vous apprendra comment générer et afficher dynamiquement des images de code bar dans votre application ASP.NET MVC en utilisant C#. Le puissant plug-in .NET pour la génération de code bar est disponible pour seulement $99.
tags:
- Barcode Reader
- Barcode Generator
- 1D Barcode
- 2D Barcode
- .NET Barcode
- Barcode SDK
- Barcode Recognition
- Barcode Generation
title: Generate and Display Barcode Image in ASP.NET MVC Application
enhanced: true
---

{{< figure align=center src="images/ASP-NET-MVC-Barcode-Generator.jpg" alt="Generate and Display Barcode Image in ASP.NET MVC">}}

Les codes barres sont essentiels pour transférer les informations sur le produit dans un format machine-readable, en utilisant des nombres et des lignes parallèles. **générer et afficher dynamiquement différents types de codes bars** Dans votre **Application ASP.NET MVC**.Cela inclut des formats populaires tels que Data Matrix, Aztec, et Code 128.A la fin de ce tutoriel, vous aurez un fonctionnel complet **Générateur de code bar ASP.NET MVC** Prêt pour vos projets, nous allons nous plonger !

## Table des contenus

1. [Les fonctionnalités du générateur de code ASP.NET MVC](#features-of-aspnet-mvc-barcode-generator)
2. [C# API pour générer des codes barres dans ASP.NET MVC](#c-api-to-generate-barcode-in-aspnet-mvc)
3. [Étapes pour générer et afficher l'image de code bar](#steps-to-generate-and-display-barcode-image-in-aspnet-mvc)
4. [Générateur de code bar ASP.NET MVC](#demo-aspnet-mvc-barcode-generator)
5. [Téléchargez ASP.NET MVC Barcode Generator Code source](#download-source-code)
6. [Obtenez une licence gratuite](#get-a-free-license)
7. [Conclusion](#conclusion)

## Caractéristiques du générateur de code bar ASP.NET MVC {#features-of-aspnet-mvc-barcode-generator}

Le **Générateur de code bar ASP.NET MVC** Il offre une gamme impressionnante de caractéristiques :

1. **Support pour divers symboles de code bar**:

### [1D Barcode (Linear) Writer for .NET](https://products.aspose.net/barcode/1d-barcode-writer/)

- Code de 128
- Code 11
- Code 39
- EAN-13
- EAN-8
- ITF-14

### [2D (Matrix) Barcode Writer for .NET](https://products.aspose.net/barcode/2d-barcode-writer/)

- Code QR
- Matrix de données
- PDF 417

1. **Options de format d'image**:

- PNG
- JPEG
- BMP
- EMF
- SVG

1. **Prévisions fonctionnalités**: Voir l'image de code bar généré avant de la sauvegarder, assurer que votre **Le code barrel ASP.NET** Il répond à vos spécifications.
2. **Télécharger Capacité**: Sauver facilement l'image de code bar générée sur votre disque local pour une utilisation ultérieure, y compris les options à utiliser **Générateur de code bar** caractéristiques .

## C# API pour générer un code bar dans ASP.NET MVC {#c-api-to-generate-barcode-in-aspnet-mvc}

Pour créer des images de code bar pour afficher dans votre **Application ASP.NET MVC**,Nous allons utiliser le **Aspose.BarCode for .NET API**.Cette API puissante facilite la génération et la reconnaissance d’un large éventail de [Type de barcode](https://docs.aspose.net/barcode/getting-started/features/#key-features).Vous pouvez aussi [Téléchargez le DLL pour ASP.NET](https://releases.aspose.com/barcode/net) ou l’installer par [NuGet](https://www.nuget.org/packages/aspose.barcode) Utilisez le commandement suivant :

```shell
PM> Install-Package Aspose.BarCode 

```

## Étapes pour Gérer et afficher l'image de code bar dans ASP.NET MVC {#steps-to-genérer-and-display-barcode-image-in-aspnet-mvc}

Suivez ces étapes pour **Gérer et afficher des images de code bar dans ASP.NET MVC** Utiliser le **Aspose.BarCode 1D Barcode Writer Plugin**:

1. **Créer un nouveau projet**:Choisir le **Les applications Web ASP.NET (en anglais : .NET Framework)** Le projet Template.{{< figure align=center src="images/select_project_template.-1024x668.jpg" alt="Select project template">}}
2. **Choisir le MVC**: dans le **Créer une nouvelle application Web ASP.NET** Le dialogue, le choix **MVC** et cliquer **Créer**.{{< figure align=center src="images/Select_mvc-1024x672.png" alt="Select MVC">}}
3. **Installer Aspose.BarCode pour .NET**:ouverture le **Gestion de package** et installez le [Aspose.BarCode for .NET](https://releases.aspose.com/barcode/net) Le paquet.{{< figure align=center src="images/Install_Aspose_Barcode_Nuget-1024x597.jpg" alt="Install Aspose.BarCode for .NET">}}
4. **Créer un dossier d'images**: Ajouter un nouveau dossier nommé **Images** pour stocker les images de code bar générées.{{< figure align=center src="images/Create-Images-Folder.jpg" alt="Create Images folder">}}
5. **Créer un modèle de code bar**: dans le **Modèles** Créer un modèle nommé **Barcode** Pour les informations de code bar.{{< gist aspose-com-gists 78c04f45434d446c01e3543fdd084192 "GenerateAndDisplayBarcode_ASP.NET_MVC_Barcode.cs" >}}
6. **Ajouter la liste de la symbologie de code bar**: Créer une liste pour enregistrer les symboles de code bar supportés dans le `Barcode.cs` fichier .{{< gist aspose-com-gists 78c04f45434d446c01e3543fdd084192 "GenerateAndDisplayBarcode_ASP.NET_MVC_BarcodeType.cs" >}}
7. **Ajouter l'enumeration de format d'image**: De même, ajoutez une liste pour les formats d'image supportés.{{< gist aspose-com-gists 78c04f45434d446c01e3543fdd084192 "GenerateAndDisplayBarcode_ASP.NET_MVC_ImageType.cs" >}}
8. **Modifier le point d'affichage**:ouverture le **Voir les articles / Accueil / index.cshtml** Faites et remplacez le contenu par le script fourni.{{< gist aspose-com-gists 78c04f45434d446c01e3543fdd084192 "GenerateAndDisplayBarcode_ASP.NET_MVC_index.cshtml" >}}
9. **Actualiser HomeController**: dans le **HomeController** classe, ajoutez un nouveau résultat d'action pour gérer la demande de poste.{{< gist aspose-com-gists 78c04f45434d446c01e3543fdd084192 "GenerateAndDisplayBarcode_ASP.NET_MVC_Index.cs" >}}
10. **Ajouter Image Download Action**: La mise en œuvre d’une nouvelle action résulte dans le **HomeController** Pour gérer les demandes de téléchargement d’image.{{< gist aspose-com-gists 78c04f45434d446c01e3543fdd084192 "GenerateAndDisplayBarcode_ASP.NET_MVC_Download.cs" >}}
11. **Exécutez l’application**: Enfin, exécutez votre application pour voir votre **Générateur de code bar** dans l’action, y compris la capacité de **ASP.NET MVC Code de barre** fonctionnalité .

## Demo ASP.NET MVC Barcode Générateur

Voici une manifestation de la **Générateur de code bar ASP.NET MVC** L’application que nous avons construite :

{{< figure align=center src="images/asp-net-mvc-barcode-generator.gif" alt="Demo ASP.NET MVC Barcode Generator" caption="Demo ASP.NET MVC Barcode Generator">}}

## Télécharger ASP.NET MVC Barcode Generator Code source {#télécharger-code source}

Vous pouvez télécharger le code source complet pour **Générateur de code bar ASP.NET MVC** Application de [GitHub](https://github.com/Muzammil-khan/ASP.NET-MVC-Barcode-Generator).

## Obtenez une licence gratuite {#get-a-free-license}

Pour explorer le plugin sans aucune limitation d'évaluation, vous pouvez [Obtenez une licence temporaire gratuite](https://purchase.aspose.net/temporary-license).

## Conclusion

Dans cet article, nous avons exploré **Comment générer et afficher une image de code bar dans un ASP.NET MVC** Application : Nous avons aussi appris **Comment télécharger l'image de code bar généré** Programmément utilisé un **Générateur de code bar**.Pour plus d’informations, référence à [Aspose.BarCode for .NET Plugin Documentation](https://docs.aspose.net/barcode/).Si vous avez des questions ou avez besoin d'aide, vous vous sentez libre de vous rendre compte sur le [Forum](https://forum.aspose.net/).

Pour ceux qui sont intéressés à en savoir plus sur **Les générateurs de code bar ASP.NET**,Vous pouvez vérifier les options telles que **ASP.NET Barcode de contrôle** et explore **Générateur de code bar gratuit** la société, si vous envisagez d’intégrer une **Scanner de code bar dans l'application web ASP.NET**,Il y a des ressources disponibles pour ce détail **Comment lire le code bar dans ASP.NET C#** Effectivement !.

Pour les développeurs qui travaillent avec **Le système ASP.NET Core**,Il existe également des bibliothèques spécifiques disponibles, telles que **Générateur de code bar Core ASP.NET** et **Le scanner de code bar Core** pour faciliter les fonctionnalités de code bar dans les applications modernes. vous pouvez même trouver open source **Générateur de code bar dans le projet de code ASP.NET** sur des plateformes comme GitHub pour aider dans vos efforts de développement.

Si votre projet demande **C# Créer un code bar** fonctionnalités, vous pouvez également vouloir explorer **C# Gérer le code bar du string** des capacités fournies par diverses bibliothèques. ressources sont disponibles qui peuvent vous aider **Créer un code bar C#** Il est facile d’utiliser les bibliothèques et les cadres existants.

En outre, si vous cherchez un **ASP.NET Barcode Générateur gratuit** Il existe plusieurs solutions open source disponibles. **Les fonctions ASP.NET Barcode** peut également être utilisé pour les projets nécessitant l'impression de code bar. Enfin, pour les capacités de code bar complètes, considérer l'exploration de la **Le lecteur de code bar ASP.NET Web Application** Pour intégrer les fonctionnalités de scan de code bar sans fil.

Vous pouvez également utiliser **ASP.NET Barcode Scanner de l'entrée** pour améliorer l'efficacité de votre application. cette intégration améliorera l'expérience utilisateur en permettant l'entrée rapide des données par l'intermédiaire de l'escanner de code bar. Si vous développez un **Image de barcode API**,considérer l’exploitation des capacités de **Générateur de code bar C# Code source** pour une fonctionnalité robuste. Pour des besoins plus avancés, regardez **Générateur de code bar DLL .NET** Des options qui peuvent être intégrées sans fin dans vos projets existants.

En outre, la **Le code bar de base ASP.NET** et **Générateur de code bar Core ASP.NET** peut aider à créer des applications polyvalentes qui nécessitent des fonctionnalités de code bar. **Générateur de code bar** et **Le lecteur de code bar.NET** Il peut également être utilisé pour la gestion efficace des données et la récupération dans vos projets.

En outre, si vous cherchez à mettre en œuvre une **.Générateur de code bar .NET Core**,Découvrez les capacités de la **Le scanner de code bar Core** Pour simplifier vos processus de scan de code bar. Avec les bonnes outils et ressources, vous pouvez améliorer vos applications pour répondre efficacement aux besoins de code bar différents.

