/* Dump the full lens shading grid from an Intel aiqb (CMC chunk at 0x38). */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "ia_types.h"
#include "ia_cmc_types.h"

extern ia_cmc_t *ia_cmc_parser_init_v1(const ia_binary_data *aiqb,
				       const ia_binary_data *nvm);
extern void ia_log_init(ia_env *);

static void dummy_log(const char *fmt, va_list ap)
{
	(void)fmt;
	(void)ap;
}

int main(int argc, char **argv)
{
	ia_binary_data aiqb, nvm = { NULL, 0 };
	ia_cmc_t *cmc;
	cmc_lens_shading_correction *lsc;
	FILE *f;
	long len;
	char *buf;
	unsigned int ls, ch, y, x;

	if (argc < 3) {
		fprintf(stderr, "usage: %s <aiqb> <offset>\n", argv[0]);
		return 1;
	}

	f = fopen(argv[1], "rb");
	if (!f) {
		perror("fopen");
		return 1;
	}
	fseek(f, 0, SEEK_END);
	len = ftell(f);
	rewind(f);
	buf = malloc(len);
	if (fread(buf, 1, len, f) != (size_t)len)
		return 1;
	fclose(f);

	aiqb.data = buf + strtol(argv[2], NULL, 0);
	aiqb.size = *(unsigned int *)((char *)aiqb.data + 4);

	ia_env env = { dummy_log, dummy_log, dummy_log, dummy_log };
	ia_log_init(&env);

	cmc = ia_cmc_parser_init_v1(&aiqb, &nvm);
	if (!cmc || !cmc->cmc_lens_shading) {
		fprintf(stderr, "no lsc\n");
		return 1;
	}

	lsc = cmc->cmc_lens_shading;
	printf("# grid %u %u light_srcs %u\n", lsc->grid_width,
	       lsc->grid_height, lsc->num_light_srcs);
	for (ch = 0; ch < 4; ch++) {
		printf("# indices[%u]", ch);
		for (x = 0; x < 4; x++)
			printf(" %d", lsc->grid_indices[ch][x]);
		printf("\n");
	}

	for (ls = 0; ls < lsc->num_light_srcs; ls++) {
		cmc_lsc_grid *g = &lsc->lsc_grids[ls];

		printf("LS %u type %d rg %.4f bg %.4f cie %.4f %.4f fb %u\n", ls,
		       (int)g->source_type, g->chromaticity.r_per_g,
		       g->chromaticity.b_per_g, g->cie_coords.x, g->cie_coords.y,
		       g->fraction_bits);
		for (ch = 0; ch < 16; ch++) {
			const unsigned short *t = g->grids[ch / 4][ch % 4];

			if (!t)
				continue;
			printf("CH %u %u\n", ch / 4, ch % 4);
			for (y = 0; y < lsc->grid_height; y++) {
				for (x = 0; x < lsc->grid_width; x++)
					printf("%u%c", t[y * lsc->grid_width + x],
					       x + 1 == lsc->grid_width ? '\n' : ' ');
			}
		}
	}
	return 0;
}
