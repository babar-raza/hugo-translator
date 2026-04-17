---
title: "Sample Live - Getting Started with Metered Licensing"
description: "Sample live-test page summarizing the Aspose.Words for .NET metered licensing guide."
sample_type: "live_test"
source_url: "https://docs.aspose.com/words/net/getting-started/metered-licensing/"
---

## Purpose of Metered Licensing

The **Metered Licensing** article for Aspose.Words for .NET explains a usage‑based licensing model that works alongside traditional license files.  
Instead of deploying a license file, developers receive public and private keys that the API uses to track feature consumption.

This model is designed for scenarios where customers prefer to pay based on usage rather than a fixed license tier.  
The article highlights benefits such as flexible scaling, transparent consumption tracking, and straightforward integration into existing applications.

The content summarized here is based on `content/docs.aspose.net/words/en/getting-started/metered-licensing/_index.md` and its live version on [docs.aspose.com](https://docs.aspose.com/words/net/getting-started/metered-licensing/).

## How Metered Licensing Works

According to the guide, developers instantiate the `Metered` class and call `SetMeteredKey` once at application startup, supplying the provided public and private keys.  
The library then communicates with Aspose servers to record usage securely and determine whether the application is running in licensed or evaluation mode.

The article emphasizes that a stable Internet connection is required so that consumption can be recorded; if connectivity is lost for an extended period, the API may revert to trial mode.  
Developers can call helper methods like `IsMeteredLicensed()` and `GetConsumptionQuantity()` to check license status and monitor usage.

These behavioral details are drawn directly from the metered licensing guide in the Aspose.Words documentation set.

## Implementation Guidance and Best Practices

The metered licensing article provides a step‑by‑step example in C# showing how to configure the license and then load and save documents as usual.  
It recommends applying the license once during application startup rather than in every request or operation, to avoid unnecessary overhead.

Security guidance in the article advises developers not to embed keys directly in source code or client‑side assets.  
Instead, keys should be stored securely (for example in environment variables or secret stores) and injected into the application at runtime.

Additional samples and context are available in the Aspose.Words for .NET documentation and related GitHub repositories linked from [docs.aspose.com](https://docs.aspose.com/words/net/getting-started/metered-licensing/).
