import argparse
import vcf
import csv
import sys
import re

def parse_csq_format(vcf_reader):
    info_fields = vcf_reader.infos

    if info_fields['CSQ'] is None:
        sys.exit('Failed to extract format string from info description for tag (CSQ)')
    else:
        csq_header = info_fields['CSQ']
        format_pattern = re.compile('Format: (.*)')
        match = format_pattern.search(csq_header.desc)
        return match.group(1)

def resolve_alleles(entry):
    alleles = {}
    if entry.is_indel:
        for alt in entry.ALT:
            alt = str(alt)
            if alt[0:1] != entry.REF[0:1]:
                alleles[alt] = alt
            elif alt[1:] == "":
                alleles[alt] = '-'
            else:
                alleles[alt] = alt[1:]
    else:
        for alt in entry.ALT:
            alt = str(alt)
            alleles[alt] = alt

    return alleles

def parse_csq_entries_for_allele(csq_entries, csq_format, csq_allele):
    csq_format_array = csq_format.split('|')

    transcripts = []
    for entry in csq_entries:
        values = entry.split('|')
        transcript = {}
        for key, value in zip(csq_format_array, values):
            transcript[key] = value
        if transcript['Allele'] == csq_allele:
            transcripts.append(transcript)

    return transcripts

def resolve_consequence(consequence_string):
    consequences = {consequence.lower() for consequence in consequence_string.split('&')}
    if 'frameshift_variant' in consequences:
        consequence = 'FS'
    elif 'missense_variant' in consequences:
        consequence = 'missense'
    elif 'inframe_insertion' in consequences:
        consequence = 'inframe_ins'
    elif 'inframe_deletion' in consequences:
        consequence = 'inframe_del'
    else:
        consequence = consequence_string
    return consequence

def output_headers():
    return[
        'chromosome_name',
        'start',
        'stop',
        'reference',
        'variant',
        'gene_name',
        'transcript_name',
        'amino_acid_change',
        'ensembl_gene_id',
        'wildtype_amino_acid_sequence',
        'downstream_amino_acid_sequence',
        'variant_type',
        'protein_position',
        'transcript_fpkm',
        'gene_fpkm',
        'index'
    ]

def main(args_input = sys.argv[1:]):
    parser = argparse.ArgumentParser('pvacseq convert_vcf')
    parser.add_argument('input_file', type=argparse.FileType('r'), help='input VCF',)
    parser.add_argument('output_file', type=argparse.FileType('w'), help='output list of variants')
    parser.add_argument('-g', '--cufflinks_genes_tracking_file', type=argparse.FileType('r'), help='genes.fpkm_tracking file from Cufflinks')
    parser.add_argument('-i', '--cufflinks_isoforms_tracking_file', type=argparse.FileType('r'), help='isoforms.fpkm_tracking file from Cufflinks')
    args = parser.parse_args(args_input)

    cufflinks_genes = {}
    if args.cufflinks_genes_tracking_file is not None:
        genes_tsv_reader = csv.DictReader(args.cufflinks_genes_tracking_file, delimiter='\t')
        for row in genes_tsv_reader:
            if row['tracking_id'] not in cufflinks_genes.keys():
                cufflinks_genes[row['tracking_id']] = {}
            cufflinks_genes[row['tracking_id']][row['locus']] = row
        args.cufflinks_genes_tracking_file.close()

    cufflinks_isoforms = {}
    if args.cufflinks_isoforms_tracking_file is not None:
        isoforms_tsv_reader = csv.DictReader(args.cufflinks_isoforms_tracking_file, delimiter='\t')
        for row in isoforms_tsv_reader:
            cufflinks_isoforms[row['tracking_id']] = row
        args.cufflinks_isoforms_tracking_file.close()

    vcf_reader = vcf.Reader(args.input_file)
    if len(vcf_reader.samples) > 1:
        sys.exit('ERROR: VCF file contains more than one sample')
    tsv_writer = csv.DictWriter(args.output_file, delimiter='\t', fieldnames=output_headers())
    tsv_writer.writeheader()
    csq_format = parse_csq_format(vcf_reader)
    transcript_count = {}
    for entry in vcf_reader:
        chromosome = entry.CHROM
        start      = entry.affected_start
        stop       = entry.affected_end
        reference  = entry.REF
        alts       = entry.ALT

        alleles_dict = resolve_alleles(entry);
        for alt in alts:
            alt = str(alt)
            csq_allele = alleles_dict[alt]
            transcripts = parse_csq_entries_for_allele(entry.INFO['CSQ'], csq_format, csq_allele)
            for transcript in transcripts:
                transcript_name = transcript['Feature']
                if transcript_name in transcript_count:
                    transcript_count[transcript_name] += 1
                else:
                    transcript_count[transcript_name] = 1
                consequence = resolve_consequence(transcript['Consequence'])
                if consequence == 'FS':
                    amino_acid_change_position = transcript['Protein_position']
                else:
                    amino_acid_change_position = transcript['Protein_position'] + transcript['Amino_acids']
                gene_name = transcript['SYMBOL']
                index = '%s_%s_%s.%s.%s' % (gene_name, transcript_name, transcript_count[transcript_name], consequence, amino_acid_change_position)
                ensembl_gene_id = transcript['Gene']
                output_row = {
                    'chromosome_name'                : entry.CHROM,
                    'start'                          : entry.affected_start,
                    'stop'                           : entry.affected_end,
                    'reference'                      : entry.REF,
                    'variant'                        : alt,
                    'gene_name'                      : gene_name,
                    'transcript_name'                : transcript_name,
                    'amino_acid_change'              : transcript['Amino_acids'],
                    'ensembl_gene_id'                : ensembl_gene_id,
                    'wildtype_amino_acid_sequence'   : transcript['WildtypeProtein'],
                    'downstream_amino_acid_sequence' : transcript['DownstreamProtein'],
                    'variant_type'                   : consequence,
                    'protein_position'               : transcript['Protein_position'],
                    'index'                          : index
                }
                if transcript_name in cufflinks_isoforms.keys():
                    cufflinks_isoforms_entry = cufflinks_isoforms[transcript_name]
                    output_row['transcript_fpkm'] = cufflinks_isoforms_entry['FPKM']
                if ensembl_gene_id in cufflinks_genes.keys():
                    cufflinks_genes_entries = cufflinks_genes[ensembl_gene_id]
                    gene_fpkm = 0
                    for locus, cufflinks_genes_entry in cufflinks_genes_entries.items():
                        gene_fpkm += float(cufflinks_genes_entry['FPKM'])
                    output_row['gene_fpkm'] = gene_fpkm
                tsv_writer.writerow(output_row)

    args.input_file.close()
    args.output_file.close()

if __name__ == '__main__':
    main()
