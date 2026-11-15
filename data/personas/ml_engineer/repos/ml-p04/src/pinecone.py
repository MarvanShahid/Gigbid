import pinecone
index = pinecone.Index('docs')
index.upsert(vectors)
