import pandas as pd

papers_df=pd.read_parquet("papers/papers_metadata.parquet")

print(papers_df)
print(papers_df.columns)

# Index(['entry_id', 'updated', 'published', 'title', 'authors', 'summary',
#        'comment', 'journal_ref', 'doi', 'primary_category', 'categories',
#        'links', 'pdf_url', 'download_time', 'content', 'topic'],
#       dtype='object')