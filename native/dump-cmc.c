/* Print the colour matrices and white points of an Intel aiqb.
 *
 * Usage: dump-cmc <aiqb> <offset>
 *
 * The offset is where the parser's AIQB chunk starts, which is not always the
 * same byte in the container; aiqb.py locates it and passes it in. The last
 * block of output ("YAML ..." lines) is the machine-readable one the tuning
 * generator reads: cct, cie x/y, the two gains, nine matrix coefficients.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "ia_types.h"
#include "ia_cmc_types.h"

extern ia_cmc_t *ia_cmc_parser_init_v1(const ia_binary_data *aiqb,
				       const ia_binary_data *nvm);
extern void ia_cmc_parser_deinit(ia_cmc_t *cmc);

static void dummy_log(const char *fmt, va_list ap)
{
	(void)fmt;
	(void)ap;
}

static const char *src_name(unsigned int t)
{
	static const char *n[] = { "undefined", "fluorescent", "incandescent",
				   "hybrid", "d65", "a", "daylight", "custom" };
	return t < sizeof(n) / sizeof(*n) ? n[t] : "?";
}

static void pm(const char *tag, const float *m)
{
	printf("    %-22s %7.4f %7.4f %7.4f\n", tag,
	       m[0], m[1], m[2]);
	printf("    %-22s %7.4f %7.4f %7.4f\n", "",
	       m[3], m[4], m[5]);
	printf("    %-22s %7.4f %7.4f %7.4f\n", "",
	       m[6], m[7], m[8]);
}

static void pmi(const char *tag, const int32_t *m, double scale)
{
	printf("    %-22s %7.4f %7.4f %7.4f\n", tag,
	       m[0] / scale, m[1] / scale, m[2] / scale);
	printf("    %-22s %7.4f %7.4f %7.4f\n", "",
	       m[3] / scale, m[4] / scale, m[5] / scale);
	printf("    %-22s %7.4f %7.4f %7.4f\n", "",
	       m[6] / scale, m[7] / scale, m[8] / scale);
}

int main(int argc, char **argv)
{
	ia_binary_data aiqb, nvm = { NULL, 0 };
	ia_cmc_t *cmc;
	FILE *f;
	long len;
	char *buf;

	if (argc < 3) {
		fprintf(stderr, "usage: %s <file> <offset>\n", argv[0]);
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
	extern void ia_log_init(ia_env *);
	ia_log_init(&env);

	cmc = ia_cmc_parser_init_v1(&aiqb, &nvm);
	if (!cmc) {
		fprintf(stderr, "parser failed\n");
		return 1;
	}

	/* plain matrices */
	cmc_parsed_color_matrices_t *pcm = &cmc->cmc_parsed_color_matrices;
	if (pcm->cmc_color_matrices) {
		unsigned int n = pcm->cmc_color_matrices->num_matrices;
		unsigned int i;

		printf("== plain color matrices: %u ==\n", n);
		for (i = 0; i < n && pcm->cmc_color_matrix; i++) {
			cmc_color_matrix_t *m = &pcm->cmc_color_matrix[i];
			printf("[%u] src=%s(0x%x) chroma=(%.4f, %.4f) cie=(%.4f, %.4f)\n",
			       i, src_name(m->light_src_type), m->light_src_type,
			       m->chromaticity.r_per_g / 256.0,
			       m->chromaticity.b_per_g / 256.0,
			       m->cie_coords.x / 1024.0,
			       m->cie_coords.y / 1024.0);
			pmi("accurate", m->matrix_accurate, 1024.0);
			pmi("preferred", m->matrix_preferred, 1024.0);
		}
	} else {
		printf("== plain color matrices: none ==\n");
	}

	/* advanced matrices */
	cmc_parsed_advanced_color_matrix_t *pa =
		&cmc->cmc_parsed_advanced_color_matrix;
	printf("\n== advanced: info=%p ls=%p hue=%p ==\n",
	       (void *)pa->cmc_advanced_color_matrix_info,
	       (void *)pa->cmc_parsed_advanced_color_matrices_ls,
	       (void *)pa->hue_of_sectors);
	if (pa->cmc_advanced_color_matrix_info) {
		unsigned int nls = pa->cmc_advanced_color_matrix_info->light_sources_count;
		unsigned int ns = pa->cmc_advanced_color_matrix_info->sector_count;
		unsigned int i, s;

		printf("light_sources=%u sectors=%u\n", nls, ns);
		for (i = 0; i < nls && pa->cmc_parsed_advanced_color_matrices_ls; i++) {
			cmc_parsed_advanced_color_matrices_ls_t *ls =
				&pa->cmc_parsed_advanced_color_matrices_ls[i];
			cmc_acm_color_matrices_info_t *ci = ls->color_matrices_info;

			printf("\n--- ls %u", i);
			if (ci)
				printf(": cct=%u src=%s(0x%x) chroma=(%.4f, %.4f) cie=(%.4f, %.4f)",
				       ci->cct, src_name(ci->src_type), ci->src_type,
				       ci->chromaticity[0], ci->chromaticity[1],
				       ci->src_cie_xy[0], ci->src_cie_xy[1]);
			printf(" ---\n");
			if (ci) {
				const unsigned int *w = (const unsigned int *)ci;
				unsigned int k;

				printf("    raw:");
				for (k = 0; k < 6; k++)
					printf(" %08x", w[k]);
				printf("\n");
			}
			if (ci && ci->chromaticity[0] > 0 && ci->chromaticity[1] > 0)
				printf("    gains r=%.4f b=%.4f\n",
				       1.0 / ci->chromaticity[0],
				       1.0 / ci->chromaticity[1]);
			pm("traditional", ls->traditional_color_matrix.color_matrix);
			for (s = 0; s < ns && ls->advanced_color_matrices; s++) {
				char tag[32];
				snprintf(tag, sizeof(tag), "sector %u", s);
				pm(tag, ls->advanced_color_matrices[s].color_matrix);
			}
		}
		if (pa->hue_of_sectors) {
			printf("\nhue:");
			for (s = 0; s < ns; s++)
				printf(" %u", pa->hue_of_sectors[s]);
			printf("\n");
		}

		/* compact one-line-per-lightsource block for the yaml generator */
		for (i = 0; i < nls && pa->cmc_parsed_advanced_color_matrices_ls; i++) {
			cmc_parsed_advanced_color_matrices_ls_t *ls =
				&pa->cmc_parsed_advanced_color_matrices_ls[i];
			cmc_acm_color_matrices_info_t *ci = ls->color_matrices_info;
			const float *m = ls->traditional_color_matrix.color_matrix;
			unsigned int j;

			if (!ci)
				continue;
			printf("YAML %u %.4f %.4f %.5f %.5f", ci->cct,
			       ci->src_cie_xy[0], ci->src_cie_xy[1],
			       1.0 / ci->chromaticity[0],
			       1.0 / ci->chromaticity[1]);
			for (j = 0; j < 9; j++)
				printf(" %.5f", m[j]);
			printf("\n");
		}
	}

	ia_cmc_parser_deinit(cmc);
	return 0;
}
