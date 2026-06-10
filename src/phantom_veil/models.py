"""Data models and constants for the Phantom Veil constraint space."""

# Geographic regions for nodes
GEOGRAPHIC_REGIONS = ["Taiwan", "US", "Germany", "Singapore", "Japan"]

# Process classes by tier
PROCESS_CLASSES = {
    1: "final_assembly",
    2: "optical_alignment",
    3: "advanced_packaging",
    4: "chemical_synthesis",
}

# Resource classes by tier
RESOURCE_CLASSES = {
    1: "module",
    2: "optical_component",
    3: "substrate",
    4: "gas_chemical",
}
