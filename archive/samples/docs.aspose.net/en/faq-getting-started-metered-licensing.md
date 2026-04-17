---
title: "FAQ - Getting Started with Metered Licensing (Sample Live)"
description: "Sample live-test FAQ addressing common questions about metered licensing for Aspose.Words for .NET."
sample_type: "live_test"
source_url: "https://docs.aspose.com/words/net/getting-started/metered-licensing/"
---

## Licensing Basics

**Q1. What is metered licensing in Aspose.Words for .NET?**  
Metered licensing is a usage‑based model where you receive public and private keys instead of a traditional license file.  
The **Metered Licensing** article explains that the API tracks consumption of certain operations and bills accordingly.

**Q2. Can I use metered licensing alongside a standard license?**  
Yes. The guide notes that the metered mechanism operates alongside the regular license model.  
You can still use a traditional license file if desired, but metered keys provide additional flexibility for pay‑as‑you‑go scenarios.

## Configuration and Usage

**Q3. How do I apply a metered license in code?**  
The documentation shows how to instantiate the `Metered` class and call `SetMeteredKey` with your public and private keys, typically during application startup.  
After this setup, the rest of your document processing code can remain unchanged.

**Q4. How can I check consumption and license status?**  
According to the article, you can call `GetConsumptionQuantity()` to retrieve usage statistics and `IsMeteredLicensed()` to verify whether the application is running in licensed mode.  
These methods help you monitor consumption and detect when an application has fallen back to evaluation mode.

## Connectivity and Security

**Q5. Does metered licensing require an Internet connection?**  
Yes. The metered model relies on communication with Aspose servers to record consumption.  
The guide warns that if communication fails for an extended period, the library may revert to trial mode until connectivity is restored.

**Q6. How should I store my metered keys securely?**  
The article recommends avoiding hard‑coding keys directly in source code or client‑side assets.  
Instead, store keys in secure locations such as environment variables, configuration secrets, or dedicated secret management services, and load them at runtime.
