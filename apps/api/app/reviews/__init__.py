"""Review provider architecture (P1.6): ManualReviewProvider (always
available — manual import already exists as a plain CRUD endpoint, see
app.routers.creative's create_business_review) and GoogleReviewProvider
(honestly reports unavailable until real Google credentials exist — see
app.reviews.provider's own docstring for why no scraping/undocumented-
endpoint fallback is implemented instead)."""
