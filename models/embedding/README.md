# Embedding model — BGE-small-en-v1.5 (quantised ONNX)

384 dimensions, ~34MB. Source: https://huggingface.co/Xenova/bge-small-en-v1.5

Chosen over all-MiniLM-L6-v2 after a side-by-side on garage-assistant style
queries: MiniLM ranked "Dentist appointment" above an oil-change note for
"when do I service the vehicle" (0.233), while BGE returned vehicle-service
notes with far higher confidence (0.455-0.774 across the same query set).

BGE is asymmetric: QUERIES take the instruction prefix
"Represent this sentence for searching relevant passages: ",
stored documents do not. See Embedder.encode_query / encode.
