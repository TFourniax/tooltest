"""Source-bound descriptions using existing parsers. No execution/business truth."""
import ast
import json
from pathlib import PurePosixPath


def describe_source(row, data, extraction):
    text = data.decode('utf-8')
    result = {'authority':'OBSERVED', 'basis':'source-syntax', 'behaviors':[],
              'intent':[], 'dependencies':[], 'interfaces':[], 'omitted':{},
              'limits':['Static syntax is not executed behavior or test coverage.']}
    if row['role'] == 'declared-document':
        statements = [(line, value) for line,value in enumerate(text.splitlines(),1) if value.strip()]
        result['intent'] = [{'text':value[:400], 'truncated':len(value)>400, 'line':line,
                             'authority':'DECLARED', 'implementation':'UNKNOWN'}
                            for line,value in statements[:80]]
        result['omitted']['documentStatements'] = max(0,len(statements)-80)
        result['limits'].append('Owner declarations; matching text never establishes requirement satisfaction.')
    if row['role'] == 'manifest':
        manifest_description(row['path'], text, result)
    if not extraction['parsed']:
        return result
    if extraction['language'] == 'python':
        python_description(text, result)
    else:
        syntax_description(row['path'], data, extraction, result)
    return result


def manifest_description(path, text, result):
    try:
        if PurePosixPath(path).name == 'package.json':
            value = json.loads(text)
            for kind in ('dependencies','devDependencies','peerDependencies','optionalDependencies'):
                entries = value.get(kind)
                if isinstance(entries,dict):
                    result['dependencies'] += [{'name':name,'scope':kind,'authority':'DECLARED'} for name in sorted(entries)[:100]]
                    result['omitted'][kind] = max(0,len(entries)-100)
            for key in ('main','module','bin','scripts'):
                entry=value.get(key)
                if isinstance(entry,str): entry={key:entry}
                if isinstance(entry,dict):
                    for name,target in list(entry.items())[:16]:
                        if isinstance(target,str):
                            result['interfaces'].append({'kind':'manifest-entry-candidate','name':str(name)[:200],
                                'target':target[:300],'line':None,'authority':'DECLARED','executed':False})
        elif PurePosixPath(path).name == 'pyproject.toml':
            import tomllib
            value=tomllib.loads(text).get('project',{})
            dependencies=value.get('dependencies',[])
            if isinstance(dependencies,list):
                result['dependencies'] += [{'name':name[:300],'scope':'project.dependencies','authority':'DECLARED'} for name in dependencies[:100] if isinstance(name,str)]
                result['omitted']['dependencies'] = max(0,len(dependencies)-100)
            scripts=value.get('scripts',{})
            if isinstance(scripts,dict):
                result['interfaces'] += [{'kind':'manifest-entry-candidate','name':name[:200],'target':str(target)[:300],
                    'line':None,'authority':'DECLARED','executed':False} for name,target in list(scripts.items())[:32]]
    except (ValueError,AttributeError,TypeError):
        result['limits'].append('Manifest details unavailable or malformed; dependency use remains UNKNOWN.')


def python_description(text, result):
    tree=ast.parse(text)
    declarations=[]
    def visit_scope(nodes, prefix=''):
        for node in nodes:
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
                declarations.append((prefix+node.name,node))
            elif isinstance(node,ast.ClassDef):
                visit_scope(node.body,prefix+node.name+'.')
    visit_scope(tree.body)
    for name,node in declarations[:64]:
        for decorator in node.decorator_list:
            if (isinstance(decorator,ast.Call) and isinstance(decorator.func,ast.Attribute)
                    and decorator.func.attr.lower() in {'get','post','put','patch','delete','options','head','route'}
                    and decorator.args and isinstance(decorator.args[0],ast.Constant)
                    and isinstance(decorator.args[0].value,str) and decorator.args[0].value.startswith('/')
                    and len(result['interfaces'])<64):
                result['interfaces'].append({'kind':'http-decorator-candidate','name':decorator.func.attr,
                    'target':decorator.args[0].value[:300],'line':decorator.lineno,'authority':'INFERRED','executed':False})
        clauses=[]
        pending=list(reversed(node.body))
        while pending:
            child=pending.pop()
            if isinstance(child,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef,ast.Lambda)):
                continue
            expression=None
            if isinstance(child,(ast.If,ast.IfExp)):
                kind,expression='condition',child.test
            elif isinstance(child,ast.Return):
                kind,expression='return-expression',child.value
            elif isinstance(child,ast.Raise):
                kind,expression='raise-expression',child.exc
            if expression is not None:
                raw=ast.unparse(expression)
                clauses.append({'kind':kind,'text':raw[:300],'truncated':len(raw)>300,'line':child.lineno})
            pending.extend(reversed(list(ast.iter_child_nodes(child))))
        result['behaviors'].append({'symbol':name,'line':node.lineno,'endLine':node.end_lineno,
            'clauses':clauses[:16], 'clausesOmitted':max(0,len(clauses)-16),
            'meaning':'Conditions and returned/raised expressions in this callable scope; execution remains UNKNOWN.'})
    result['omitted']['behaviors']=max(0,len(declarations)-64)
    for node in tree.body:
        if isinstance(node,ast.If) and ast.unparse(node.test) in {"__name__ == '__main__'", "'__main__' == __name__"}:
            result['interfaces'].append({'kind':'entry-guard','name':'Python main guard','target':ast.unparse(node.test),
                                         'line':node.lineno,'authority':'OBSERVED','executed':False})


def syntax_description(path, data, extraction, result):
    from .structure_catalog import SPECS
    from .structure_syntax import captured_syntax_tree
    captured=captured_syntax_tree(data,SPECS[PurePosixPath(path).suffix])
    if captured is None:
        result['limits'].append('Description parser exhausted its budget; symbol extraction remains separately scoped.')
        return
    _,nodes=captured
    for symbol in extraction['symbols'][:64]:
        clauses=[]
        for node in nodes:
            line=node.start_point.row+1
            if not symbol['line']<=line<=symbol['end_line']: continue
            kind={'if_statement':'condition','return_statement':'return-expression',
                  'throw_statement':'raise-expression'}.get(node.type)
            if kind:
                expr=node.child_by_field_name('condition') if kind=='condition' else node
                if expr is None: expr=node
                raw=data[expr.start_byte:expr.end_byte].decode('utf-8')
                clauses.append({'kind':kind,'text':raw[:300],'truncated':len(raw)>300,'line':line})
        result['behaviors'].append({'symbol':symbol['qualified_name'],'line':symbol['line'],'endLine':symbol['end_line'],
            'clauses':clauses[:16], 'clausesOmitted':max(0,len(clauses)-16),
            'meaning':f"Observed {symbol['kind']} syntax and contained expressions; call scope/order and responsibility require review."})
    result['omitted']['behaviors']=max(0,len(extraction['symbols'])-64)
    for node in nodes:
        if node.type!='call_expression': continue
        function=node.child_by_field_name('function')
        args=node.child_by_field_name('arguments')
        if function is None or args is None: continue
        member=function.child_by_field_name('property')
        if member is None: continue
        method=data[member.start_byte:member.end_byte].decode('utf-8')
        first=next(iter(args.named_children),None)
        if method.lower() not in {'get','post','put','patch','delete','options','head'} or first is None or first.type!='string': continue
        target=data[first.start_byte:first.end_byte].decode('utf-8')
        if not target[1:].startswith('/'): continue
        result['interfaces'].append({'kind':'http-method-call-candidate','name':method,'target':target[:300],
            'line':node.start_point.row+1,'authority':'INFERRED','executed':False})
        if len(result['interfaces'])>=64:
            result['limits'].append('Interface candidates limited to 64; completeness UNKNOWN.')
            break
