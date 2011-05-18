from sqlalchemy.orm import mapper, relation
from sqlalchemy import and_
from sqlalchemy import select
from tables import *
import datetime

def add_init(myclass):

    def init_standard(self, **kwargs): 
        # we go through all arguments given as keywords and set them 
        # e.g. if init was called with (id=someid) we set here self.id = someid
        for k in kwargs:
            setattr( self, k, kwargs[k])

    def init_with_defaults(self, **kwargs): 
        for d in self.__class__.__defaults: setattr( self, d, self.__class__.__defaults[d])
        self.insert_date = datetime.datetime.utcnow().strftime('%Y-%m-%d')

        # we go through all arguments given as keywords and set them 
        # e.g. if init was called with (id=someid) we set here self.id = someid
        for k in kwargs:
            setattr( self, k, kwargs[k])

    print "setting up init"
    print myclass.__dict__
    if myclass.__dict__.has_key('__defaults'): myclass.__init__ = init_with_defaults
    else:                                      myclass.__init__ = init_standard
    return myclass

def add_addfxn(myclass):

    #generic addignore
    def addignore_setid(self, session):
        p = self.exists(session)
        if p is None: return self.add(session)
        else: return p

    #generic exist, will only check whether this id is already present
    def exists(self, session):
        return session.query(self.__class__).filter_by(id=self.id).first()

    #generic add, will just use session
    def add(self, session):
        session.add(self)
        session.commit()
        return self

    if not myclass.__dict__.has_key('add'):             myclass.add = add
    if not myclass.__dict__.has_key('exists'):          myclass.exists = exists
    if not myclass.__dict__.has_key('addignore_setid'): myclass.addignore_setid = addignore_setid

    return myclass

def add_mapper(table):
    def wrap(myclass):
        mapper(myclass, table)
        return myclass
    return wrap

@add_mapper(genome_table)
@add_addfxn
@add_init
class Genome(object): 
    pass

@add_mapper(genomeSeq_table)
@add_addfxn
@add_init
class GenomeSeq(object): 
    def _get_seq(self):
        proxy = db_genome.execute( 'select uncompress(compress_seq) from \
                                  genomeSeq where id =  %s' % self.id)
        return list(proxy)[0][0]
    def _set_seq(self, text):
        self.compress_seq = func.compress(text)

@add_mapper(sequence_table)
@add_addfxn
@add_init
class Sequence(object): 

    def addignore_setid(self, session, db):
        cursor = db.cursor()
        exists = self.exists(cursor)
        if exists == 0: return self.add(session, db)
        else: return session.query(Sequence).filter_by(id=exists).first()  

    def add(self, session, db):
        cursor = db.cursor()
        res = cursor.execute( "insert into ddbMeta.sequence (sha1, sequence) " + \
            "VALUES (sha1(upper('%s')), upper('%s') ) " % ( self.sequence , self.sequence))
        insert_id = db.insert_id()
        return session.query(Sequence).filter_by(id=insert_id).first()

    def exists(self, cursor): 
        res = cursor.execute( "select id from ddbMeta.sequence where sha1 = sha1(UPPER('%s')) " % self.sequence )
        if res == 0: return 0
        return cursor.fetchone()[0]

    def __repr__(self):
        if self.sequence and len(self.sequence) > 80:
            rseq = self.sequence[:40] + '...' +  self.sequence[-40:]
        else: rseq = self.sequence
        return "<Sequence(id '%s', '%s', sequence '%s')>" % (self.id, self.sha1, rseq)

@add_init
@add_addfxn
class Feature(object): 

    ___defaults = { 
        'mol_type'      : '',
        'db_xref'       : '',   
        'gene'          : '',   
        'locus_tag'     : '',   
        'note'          : '',   
        'codon_start'   : '',   
        'transl_table'  : '',   
        'product'       : '',   
        'protein_id'    : '',   
        'ec_number'     : '',   
        'gene_synonym'  : '',   
        'function'      : '',   
    }

    def __repr__(self):
       return "<Feature(id '%s', genome '%s', seq '%s', '%s', '%s', '%s', '%s', '%s')>" % (self.id, self.genome_key, self.sequence_key, self.strand, self.type, self.start, self.end, self.gene )

mapper(Feature, feature_table , properties = {
    'sequence' : relation (Sequence, primaryjoin=
        feature_table.c.sequence_key==sequence_table.c.id, 
        foreign_keys=[feature_table.c.sequence_key]) } )
 
@add_mapper(peptide_table)
@add_addfxn
@add_init
class Peptide(object):
    def __repr__(self):
       return "<Peptide('%s','%s','%s')>" % (self.id, self.experiment_key, self.sequence )

    def exists(self, session):
        return session.query(self.__class__).filter_by(sequence=self.sequence, experiment_key=self.experiment_key).first()

@add_mapper(gene_table)
@add_addfxn
@add_init
class Gene(object):
    def __repr__(self):
       return "<Gene('%s','%s','%s')>" % (self.id, self.experiment_key, self.description )

@add_addfxn
@add_init
class Protein(object):

    def exists(self, session):
        return session.query(Protein).filter_by(experiment_key=self.experiment_key, sequence_key=self.sequence_key).first()

    def get_tryptic_peptides(self, min=5, max=60):
        start = 0
        for i,c in enumerate(self.sequence.sequence):
            prev = self.sequence.sequence[i-1]
            if i > 0 and c != 'P' and (prev == 'K' or prev == 'R'):
                pseq = self.sequence.sequence[start:i]
                start = i
                if len(pseq) < min or len(pseq) > max: continue
                pep = Peptide(experiment_key=self.experiment_key, sequence=pseq,
                    peptide_type='bioinformatics', parent_sequence_key = self.sequence.id, 
                    molecular_weight=-1, pi=-1)
                self.peptides.append( pep )

    def delete_peptides(self, session):
        for pep in self.peptides: session.delete(pep)
        session.commit()

    def __repr__(self):
       return "<Protein('%s','%s','%s')>" % (self.id, self.experiment_key, self.sequence )

mapper(Protein, protein_table, properties = {
    'sequence' : relation (Sequence, 
        primaryjoin=protein_table.c.sequence_key==sequence_table.c.id, 
        backref='proteins',
        foreign_keys=[protein_table.c.sequence_key]), 
    'peptides' : relation(Peptide, secondary=protPepLink_table,
        primaryjoin=protein_table.c.id==protPepLink_table.c.protein_key, 
        secondaryjoin=and_(protPepLink_table.c.peptide_key==peptide_table.c.id),
        backref='proteins', 
        foreign_keys=[protPepLink_table.c.protein_key, protPepLink_table.c.peptide_key]),
    'genes' : relation(Gene, secondary=geneProtLink_table,
        primaryjoin=protein_table.c.id==geneProtLink_table.c.protein_key, 
        secondaryjoin=and_(geneProtLink_table.c.gene_key==gene_table.c.id),
        backref='proteins', 
        foreign_keys=[geneProtLink_table.c.protein_key, geneProtLink_table.c.gene_key]),
    }, 
)