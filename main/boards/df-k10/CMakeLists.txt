# Ensure the assembler alias file is compiled for this board directory (if included by glob it is redundant, but safe)
idf_component_get_property(main_dir main COMPONENT_DIR)
